"""
Ideation Evidence Planner (Phase 1 — Shadow Deterministic Evidence Planner)
================================================================================
용준/Claude(2026-07-23). 아이디어 회의(ideation-conversation) 전문가 발언을 생성하기
"전에" 규칙 기반으로 이번 턴에 쓸 evidence를 확정하는 planner.

실제 병목(로그 확인): retrieval 자체는 성공해도(target_count>0) 답변 생성 모델이 검색된
근거를 인용하지 않고 expert_judgment만 만드는 턴이 대부분이다(6턴 중 5턴이
evidence_status="expert_judgment_only"). Phase 1은 이 문제를 고치지 않는다 — 대신
"결정적 규칙만으로 적절한 evidence를 실제로 골라낼 수 있는가"를 shadow(그림자) 모드로
검증한다: 이 모듈이 만든 계획(EvidencePlan)은 prompt/claims/grounding/routing 어디에도
쓰이지 않고, 호출부(ai/meeting/graph/ideation_conv_nodes.py::make_conv_discussion_node)가
trace 로그로만 기록한다.

ai/meeting은 이 모듈을 import하지 않는다 — ai/meeting/graph는 backend가 주입하는
Callable(plain dict 입출력)의 "모양"만 안다(evidence_lookup/ground_claims와 동일한 경계
원칙, ai/rag/tests/test_meeting_evidence_service.py::TestScopeBoundary가 강제).

관련성 판정에 대해: ai.rag.evidence_linking.relevance.is_relevant_candidate()는 사후
claim-grounding용(생성된 claim 문장과 인용된 청크의 관련성)이라 여기서는 하드 게이트로
쓰지 않는다 — 의미 있는 keyword가 없으면 자동 통과하고, role keyword 하나만 겹쳐도 통과하는
등 "이 턴에 쓸 evidence를 미리 고르는" 목적에는 느슨하다. 그 결과는 legacy_relevance_pass로
진단용으로만 남기고, 실제 채택 여부는 별도 issue_relevance_score(질의문 vs 청크 키워드
겹침, calculate_relevance_score 재사용) 임계값으로 판단한다.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Optional

from ai.rag.evidence_linking.config import EvidenceLinkingConfig
from ai.rag.evidence_linking.relevance import calculate_relevance_score, extract_keywords, is_relevant_candidate

POLICY_VERSION = "ideation-planner-v3"

# 이 값 미만이면 "이번 쟁점의 실제 질의문과 무관하다"고 보고 제외한다 — calculate_relevance_score는
# 0~1 근사치이고, claim_grounding의 EvidenceLinkingConfig.min_relevance_score(0.1, 사후 검증용
# 느슨한 값)와는 별개로 planner 전용 임계값을 둔다(요청: 기존 threshold를 임의로 낮추지 않고
# 새 임계값은 상수로 명시).
MIN_ISSUE_RELEVANCE_SCORE: float = 0.15

# 역할별로 selected_evidence에 담을 최대 개수(공통 정책 — 요청 9번: "역할이 다르더라도 동일
# target을 보는 것은 정상"이므로 role별로 독립적으로 계산한다).
_ROLE_MAX_SELECTION: dict[str, int] = {"target": 1, "criteria": 1}

# planning_expert가 criteria를 채택하려면 issue 제목이 이 키워드 중 하나와 직접 관련돼야
# 한다(요청 9번: "criteria가 단순히 검색됐다는 이유로 선택하지 않는다"). dev_expert도 동일한
# 원칙의 별도 키워드 집합을 쓴다. 이 목록은 결정적 정책이며 하나의 임의 가중합으로 숨기지
# 않는다 — role_policy_pass 탈락 사유로 그대로 로그에 남는다.
_PLANNING_CRITERIA_ISSUE_KEYWORDS = (
    "문제",
    "대상 사용자",
    "사용자 가치",
    "고객 가치",
    "핵심 가치",
    "차별",
    "공모전",
    "심사",
    "적합성",
    "사업성",
    "계획",
    "목표",
    "KPI",
    "데이터",
    "통합",
    "AI 역할",
    "운영",
    "사회적 가치",
    "지속 가능",
    "거버넌스",
)
_DEV_CRITERIA_ISSUE_KEYWORDS = (
    "문제 정의",
    "실현 가능",
    "기술",
    "데이터",
    "안전",
    "적용성",
    "mvp",
    "MVP",
    "성능",
    "보안",
)

_CLAIM_TYPE_BY_ROLE: dict[str, str] = {"target": "user_provided_fact", "criteria": "document_fact"}

_SHADOW_HISTORY_KEEP = 20

_SENTENCE_END_RE = re.compile(r"[.?!]")
_BULLET_PREFIX_RE = re.compile(r"^\s*[-*•·]\s+")


def _role_allows_criteria_for_issue(persona_id: str, issue_title: str) -> bool:
    """공통 정책(요청 9번) — criteria는 현재 issue와 역할별로 직접 관련될 때만 채택 후보가
    된다. 매핑에 없는 persona_id(진행자 등)는 이 planner 자체를 호출하지 않으므로 여기서는
    다루지 않는다."""
    if persona_id == "planning_expert":
        keywords = _PLANNING_CRITERIA_ISSUE_KEYWORDS
    elif persona_id == "dev_expert":
        keywords = _DEV_CRITERIA_ISSUE_KEYWORDS
    else:
        return False
    return any(keyword in issue_title for keyword in keywords)


def resolve_retrieval_score(item: dict) -> tuple[Optional[float], Optional[str]]:
    """final_score -> semantic_score -> score 우선순위로 검색 점수를 조회한다. 셋 다 없으면
    (None, "missing_retrieval_score")를 반환해 호출부가 그 항목을 제외하게 한다."""
    for key in ("final_score", "semantic_score", "score"):
        value = item.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value), None
    return None, "missing_retrieval_score"


def evaluate_evidence_eligibility(
    item: dict,
    *,
    persona_id: str,
    effective_issue: dict,
    runtime_scope: dict,
    config: Optional[EvidenceLinkingConfig] = None,
) -> dict:
    """retrieved_evidence 항목 1건이 이번 턴 evidence 후보로 적격한지 결정적으로 판정한다.
    각 신호를 개별 필드로 노출해(요청: 임의 가중합 하나로 숨기지 않는다) 탈락 사유를
    exclusion_reasons에 남긴다."""
    cfg = config or EvidenceLinkingConfig()
    exclusion_reasons: list[str] = []

    ref = item.get("ref")
    chunk_id = item.get("chunk_id")
    document_id = item.get("document_id")
    text = item.get("text") or item.get("quote") or ""
    structural_valid = bool(
        isinstance(ref, str)
        and ref
        and isinstance(chunk_id, str)
        and chunk_id
        and isinstance(document_id, str)
        and document_id
        and isinstance(text, str)
        and text.strip()
    )
    if not structural_valid:
        exclusion_reasons.append("structurally_invalid")

    document_role = item.get("document_role")
    role_policy_pass = True
    if document_role not in ("target", "criteria"):
        role_policy_pass = False
        exclusion_reasons.append("unsupported_document_role")
    elif document_role == "criteria" and not _role_allows_criteria_for_issue(
        persona_id, effective_issue.get("title") or ""
    ):
        role_policy_pass = False
        exclusion_reasons.append("criteria_not_relevant_to_issue")

    scope_valid = True
    ideation_source_type = item.get("ideation_source_type")
    if ideation_source_type == "ideation_candidate":
        selected_candidate_document_id = runtime_scope.get("selected_candidate_document_id")
        if not selected_candidate_document_id or item.get("document_id") != selected_candidate_document_id:
            scope_valid = False
            exclusion_reasons.append("candidate_scope_mismatch")
    elif ideation_source_type == "user_session_answer":
        session_id = runtime_scope.get("session_id")
        if not session_id or item.get("session_id") != session_id:
            scope_valid = False
            exclusion_reasons.append("session_scope_mismatch")

    retrieval_score, score_reason = resolve_retrieval_score(item)
    if score_reason:
        exclusion_reasons.append(score_reason)
        retrieval_score_pass = False
    else:
        retrieval_score_pass = retrieval_score >= cfg.min_evidence_score
        if not retrieval_score_pass:
            exclusion_reasons.append("below_retrieval_score")

    issue_query = effective_issue.get("query") or effective_issue.get("title") or ""
    issue_relevance_score = calculate_relevance_score(
        issue_query,
        text,
        section_title=item.get("section"),
        document_title=item.get("document_name"),
    )
    legacy_relevance_pass = is_relevant_candidate(
        issue_query,
        text,
        section_title=item.get("section"),
        document_title=item.get("document_name"),
        config=cfg,
    )
    issue_relevance_pass = issue_relevance_score >= MIN_ISSUE_RELEVANCE_SCORE
    if not issue_relevance_pass:
        exclusion_reasons.append("below_issue_relevance")

    eligible = (
        structural_valid
        and scope_valid
        and retrieval_score_pass
        and role_policy_pass
        and issue_relevance_pass
    )

    return {
        "ref": ref,
        "structural_valid": structural_valid,
        "scope_valid": scope_valid,
        "retrieval_score_pass": retrieval_score_pass,
        "retrieval_score": retrieval_score,
        "issue_relevance_score": issue_relevance_score,
        "issue_relevance_pass": issue_relevance_pass,
        "legacy_relevance_pass": legacy_relevance_pass,
        "role_policy_pass": role_policy_pass,
        "eligible": eligible,
        "exclusion_reasons": exclusion_reasons,
    }


def _iter_line_spans(content: str) -> list[tuple[int, int]]:
    """content를 줄바꿈 단위로 나눠 (원문 기준 start, end) span을 낸다. 빈 줄은 건너뛴다."""
    spans: list[tuple[int, int]] = []
    offset = 0
    for line in content.splitlines(keepends=True):
        stripped_len = len(line.rstrip("\r\n"))
        line_body = line[:stripped_len]
        if line_body.strip():
            leading_ws = len(line_body) - len(line_body.lstrip())
            spans.append((offset + leading_ws, offset + stripped_len))
        offset += len(line)
    return spans


def _iter_sentence_spans(content: str, line_start: int, line_end: int) -> list[tuple[int, int]]:
    """한 줄(line_start:line_end) 안에서 문장 종결 기호(.?!) 단위로 span을 더 쪼갠다. 글머리
    기호(bullet)는 문장 내용에서 제외한다(quote에 "- "가 그대로 남지 않도록)."""
    text = content[line_start:line_end]
    bullet_match = _BULLET_PREFIX_RE.match(text)
    cursor = bullet_match.end() if bullet_match else 0
    spans: list[tuple[int, int]] = []
    for match in _SENTENCE_END_RE.finditer(text):
        end = match.end()
        if end <= cursor:
            continue
        if text[cursor:end].strip():
            spans.append((line_start + cursor, line_start + end))
        cursor = end
    if text[cursor:].strip():
        spans.append((line_start + cursor, line_start + len(text)))
    return spans


def _candidate_spans(content: str) -> list[tuple[int, int]]:
    """quote 후보 구간을 줄바꿈/글머리 단위로 먼저 나누고, 각 줄 안에서 문장 단위로 다시
    나눈다(요청: "마침표/물음표/느낌표뿐 아니라 줄바꿈·bullet 단위도 후보로 분리")."""
    spans: list[tuple[int, int]] = []
    for line_start, line_end in _iter_line_spans(content):
        spans.extend(_iter_sentence_spans(content, line_start, line_end))
    return spans


def extract_planner_quote(content: str, query: str) -> Optional[tuple[str, int, int]]:
    """content에서 query와 가장 관련 있는 원문 구간을 그대로 잘라 반환한다(quote, start, end).
    quote_extractor.extract_quote()와 달리 관련 구간을 못 찾으면 청크 앞부분으로 폴백하지
    않는다 — 관련성 없는 fallback quote를 계획에 담지 않기 위해서다(요청 사항 그대로).
    반환값이 None이면 이 청크는 quote 추출 실패로 제외해야 한다."""
    if not content or not content.strip():
        return None
    query_tokens = extract_keywords(query)
    if not query_tokens:
        return None

    best_span: Optional[tuple[int, int]] = None
    best_score = 0
    for start, end in _candidate_spans(content):
        segment_tokens = extract_keywords(content[start:end])
        score = len(query_tokens & segment_tokens)
        if score > best_score:
            best_score = score
            best_span = (start, end)
    if best_span is None:
        return None

    raw_start, raw_end = best_span
    segment = content[raw_start:raw_end]
    lstripped = segment.lstrip()
    leading_ws = len(segment) - len(lstripped)
    quote = lstripped.rstrip()
    if not quote:
        return None
    start = raw_start + leading_ws
    end = start + len(quote)
    assert content[start:end] == quote  # exact substring invariant
    return quote, start, end


def _selection_reason_code(persona_id: str, document_role: str, reused: bool) -> str:
    base = "target_fact_for_current_issue" if document_role == "target" else "criteria_fact_for_current_issue"
    return f"{base}_reused" if reused else base


def _empty_plan(plan_id: str, persona_id: str, issue: dict, reason: str) -> dict:
    return {
        "plan_id": plan_id,
        "policy_version": POLICY_VERSION,
        "persona_id": persona_id,
        "issue": issue,
        "eligible_evidence_count": 0,
        "grounded_claim_required": False,
        "expert_judgment_required": True,
        "selected_evidence": [],
        "empty_plan_reason": reason,
        "validation": {"valid": True, "errors": []},
    }


def validate_evidence_plan(
    plan: dict,
    *,
    retrieved_evidence: list[dict],
    runtime_scope: dict,
) -> dict:
    """이미 만들어진 plan을 retrieved_evidence/runtime_scope와 대조해 결정적으로 재검증한다
    (요청: "생성된 plan을 로그에 남기기 전에 결정적으로 검증"). ref 존재 여부부터 quote
    invariant까지 하드 룰만 검사하고, 실패한 plan은 valid=false로 표시한다 — Phase 1에서는
    valid 여부와 무관하게 prompt에는 절대 쓰이지 않고 로그로만 남는다."""
    errors: list[str] = []
    by_ref = {item.get("ref"): item for item in retrieved_evidence if isinstance(item, dict) and item.get("ref")}
    seen_refs: set[str] = set()
    seen_chunk_ids: set[str] = set()
    role_counts: dict[str, int] = {}

    for evidence in plan.get("selected_evidence") or []:
        ref = evidence.get("ref")
        source = by_ref.get(ref)
        if source is None:
            errors.append(f"unknown_ref:{ref}")
            continue

        if source.get("chunk_id") != evidence.get("chunk_id") or source.get("document_id") != evidence.get(
            "document_id"
        ):
            errors.append(f"chunk_document_mismatch:{ref}")

        ideation_source_type = source.get("ideation_source_type")
        if ideation_source_type == "ideation_candidate":
            selected_candidate_document_id = runtime_scope.get("selected_candidate_document_id")
            if not selected_candidate_document_id or source.get("document_id") != selected_candidate_document_id:
                errors.append(f"scope_violation:{ref}")
        elif ideation_source_type == "user_session_answer":
            session_id = runtime_scope.get("session_id")
            if not session_id or source.get("session_id") != session_id:
                errors.append(f"scope_violation:{ref}")

        role = evidence.get("document_role")
        if role not in _CLAIM_TYPE_BY_ROLE:
            errors.append(f"unsupported_document_role:{ref}")
        elif evidence.get("claim_type") != _CLAIM_TYPE_BY_ROLE[role]:
            errors.append(f"claim_type_mismatch:{ref}")

        if role is not None:
            role_counts[role] = role_counts.get(role, 0) + 1
            if role_counts[role] > _ROLE_MAX_SELECTION.get(role, 1):
                errors.append(f"role_limit_exceeded:{role}")

        if ref in seen_refs:
            errors.append(f"duplicate_ref:{ref}")
        seen_refs.add(ref)
        chunk_id = evidence.get("chunk_id")
        if chunk_id in seen_chunk_ids:
            errors.append(f"duplicate_chunk_id:{chunk_id}")
        seen_chunk_ids.add(chunk_id)

        quote = evidence.get("quote")
        start = evidence.get("quote_start")
        end = evidence.get("quote_end")
        content = source.get("text") or source.get("quote") or ""
        if not isinstance(quote, str) or not quote.strip():
            errors.append(f"empty_quote:{ref}")
        elif (
            not isinstance(start, int)
            or not isinstance(end, int)
            or isinstance(start, bool)
            or isinstance(end, bool)
            or content[start:end] != quote
        ):
            errors.append(f"quote_offset_invariant_failed:{ref}")

        if not evidence.get("selection_reason_code"):
            errors.append(f"missing_selection_reason:{ref}")

    return {"valid": not errors, "errors": errors}


def build_evidence_plan(
    *,
    persona_id: str,
    effective_issue: dict,
    retrieved_evidence: list[dict],
    runtime_scope: dict,
    shadow_history: Optional[list[dict]] = None,
    config: Optional[EvidenceLinkingConfig] = None,
) -> dict:
    """이번 턴에 쓸 evidence를 규칙 기반으로 확정한다(EvidencePlan, 항상 plain dict).
    shadow_history는 같은 speaker/issue에서 이전에 선택된 chunk_id 목록(dict: chunk_id 키
    포함) — 반복 사용 여부만 표시할 뿐 후보에서 제외하지는 않는다(요청 8번: 유일한 적격
    근거라면 제거하지 말고 reused로 표시)."""
    cfg = config or EvidenceLinkingConfig()
    plan_id = f"EP-{uuid.uuid4().hex[:10]}"
    issue = {
        "issue_id": effective_issue.get("issue_id", ""),
        "title": effective_issue.get("title", ""),
        "query": effective_issue.get("query", ""),
    }

    if not retrieved_evidence:
        return _empty_plan(plan_id, persona_id, issue, "no_retrieved_evidence")

    evaluations = [
        (item, evaluate_evidence_eligibility(item, persona_id=persona_id, effective_issue=issue, runtime_scope=runtime_scope, config=cfg))
        for item in retrieved_evidence
        if isinstance(item, dict)
    ]
    if not evaluations:
        return _empty_plan(plan_id, persona_id, issue, "no_retrieved_evidence")

    if not any(e["structural_valid"] for _, e in evaluations):
        return _empty_plan(plan_id, persona_id, issue, "no_structurally_valid_evidence")

    if not any(e["structural_valid"] and e["scope_valid"] for _, e in evaluations):
        return _empty_plan(plan_id, persona_id, issue, "no_scope_valid_evidence")

    if not any(e["structural_valid"] and e["scope_valid"] and e["retrieval_score_pass"] for _, e in evaluations):
        return _empty_plan(plan_id, persona_id, issue, "below_retrieval_score")

    eligible = [(item, e) for item, e in evaluations if e["eligible"]]
    if not eligible:
        score_passing = [
            e for _, e in evaluations if e["structural_valid"] and e["scope_valid"] and e["retrieval_score_pass"]
        ]
        if any(not e["role_policy_pass"] for e in score_passing):
            reason = "role_policy_excluded_all"
        else:
            reason = "no_issue_relevant_evidence"
        return _empty_plan(plan_id, persona_id, issue, reason)

    history_chunk_ids = {h.get("chunk_id") for h in (shadow_history or []) if h.get("chunk_id")}

    def sort_key(pair: tuple[dict, dict]):
        item, evaluation = pair
        reused = item.get("chunk_id") in history_chunk_ids
        return (
            1 if reused else 0,
            -evaluation["issue_relevance_score"],
            -(evaluation["retrieval_score"] or 0.0),
            item.get("chunk_id") or "",
        )

    ordered = sorted(eligible, key=sort_key)

    role_counts: dict[str, int] = {}
    selected: list[dict] = []
    for item, evaluation in ordered:
        role = item.get("document_role")
        if role_counts.get(role, 0) >= _ROLE_MAX_SELECTION.get(role, 0):
            continue
        content = item.get("text") or item.get("quote") or ""
        extraction = extract_planner_quote(content, issue["query"] or issue["title"])
        if extraction is None:
            continue
        quote, quote_start, quote_end = extraction
        reused = item.get("chunk_id") in history_chunk_ids
        selected.append(
            {
                "ref": item.get("ref"),
                "chunk_id": item.get("chunk_id"),
                "document_id": item.get("document_id"),
                "document_role": role,
                "claim_type": _CLAIM_TYPE_BY_ROLE[role],
                "quote": quote,
                "quote_start": quote_start,
                "quote_end": quote_end,
                "retrieval_score": evaluation["retrieval_score"],
                "issue_relevance_score": evaluation["issue_relevance_score"],
                "selection_reason_code": _selection_reason_code(persona_id, role, reused),
                "reused_in_same_issue": reused,
            }
        )
        role_counts[role] = role_counts.get(role, 0) + 1

    if not selected:
        return _empty_plan(plan_id, persona_id, issue, "quote_extraction_failed")

    plan = {
        "plan_id": plan_id,
        "policy_version": POLICY_VERSION,
        "persona_id": persona_id,
        "issue": issue,
        "eligible_evidence_count": len(eligible),
        "grounded_claim_required": True,
        "expert_judgment_required": False,
        "selected_evidence": selected,
        "empty_plan_reason": None,
        "validation": {"valid": True, "errors": []},
    }
    validation = validate_evidence_plan(plan, retrieved_evidence=retrieved_evidence, runtime_scope=runtime_scope)
    plan["validation"] = validation
    if not validation["valid"]:
        plan["empty_plan_reason"] = "plan_validation_failed"
    return plan


__all__ = [
    "POLICY_VERSION",
    "MIN_ISSUE_RELEVANCE_SCORE",
    "resolve_retrieval_score",
    "evaluate_evidence_eligibility",
    "extract_planner_quote",
    "validate_evidence_plan",
    "build_evidence_plan",
]
