# 작성자: 용준/Claude(2026-07-21)
# 목적: 대화형 아이디어 발전 회의(ideation-conversation)의 discovery(아이디어 발굴) 모드
#       전용 LangGraph 노드. 초기 아이디어가 없는 사용자를 위해 기획 전문가가 후보 2~3개를
#       만들고(candidate_planning), 개발 전문가가 후보별 실현 가능성을 검토해 병합하고
#       (candidate_feasibility), 사용자의 선택/결합/재추천/전문가추천 요청을 처리해
#       (candidate_selection) 최종적으로 refinement의 첫 phase("planning_question")로
#       합류시킨다. refinement 전용 노드(ideation_conv_nodes.py)는 이 파일이 건드리지 않고
#       그대로 재사용한다(_build_message/_safe_call_structured_json/_blank/_last_user_answer).
# import: prompts.build_ideation_conv_candidate_*(형제 패키지), 같은 패키지의
#         ideation_conv_state/ideation_conv_nodes/llm.

from __future__ import annotations

import re
from typing import Any, Callable

from prompts import (
    build_ideation_conv_candidate_feasibility_prompt,
    build_ideation_conv_candidate_planning_prompt,
    build_ideation_conv_candidate_selection_prompt,
)

from .ideation_conv_nodes import (
    _blank,
    _bullets,
    _build_message,
    _last_user_answer,
    _safe_call_structured_json,
)
from .ideation_conv_state import IdeationConvState
from .ideation_nodes import EvidenceLookup
from .llm import LLMCall

# 요청: "후보 재생성이 무한 반복되거나 LLM 호출 제한을 우회하지 못하도록 상한을 두세요."
# 재질문 상한(_MAX_ANSWER_RETRY)과 같은 원칙 — 상한 도달 시 LLM을 아예 호출하지 않고
# 코드가 즉시 안내 메시지로 막는다(무한 루프뿐 아니라 LLM 호출 자체를 원천 차단).
_MAX_CANDIDATE_REGENERATIONS = 2

_VALID_FEASIBILITY = {"high", "medium", "low"}
_VALID_RESOLUTIONS = {"select", "combine", "recommend", "unclear"}
# 결합(combine) 해석 시 merge_analysis.fit이 가질 수 있는 값 — feasibility와 값 집합은
# 같지만(high/medium/low) 의미가 다르므로(실현 가능성이 아니라 "결합 적합도") 별도 상수로
# 분리한다.
_VALID_MERGE_FIT = {"high", "medium", "low"}
_REQUIRED_CANDIDATE_FIELDS = (
    "title",
    "problem",
    "target_user",
    "usage_scenario",
    "core_value",
    "solution",
    "differentiation",
    "contest_fit",
)
_REQUIRED_IDEA_FIELDS = ("title", "problem", "target_user", "solution")

_SELECTION_QUESTION = (
    "제안된 후보 중 발전시키고 싶은 아이디어를 선택해 주세요. 번호나 제목을 입력하거나, "
    "'1번과 2번 결합', '다시 추천', '전문가 추천'처럼 답할 수 있습니다."
)

_REGENERATE_KEYWORDS = ("다시 추천", "다른 후보", "재추천", "다시 만들어", "다시 제안", "새로운 후보")

# "1", "1번", "1번째", "candidate_1", "candidate 1" 처럼 순수하게 번호만 가리키는 경우만
# 코드가 결정적으로 처리한다 — 문장이 더 길거나 다른 말이 섞여 있으면(예: "1번인데 2번
# 기능도 넣고 싶어요") LLM 해석으로 넘긴다(요청: 단순 선택은 코드로, 자연어 결합/수정 요청은
# LLM으로).
_NUMERIC_SELECT_RE = re.compile(r"^(candidate[_\s]?)?([1-3])\s*(번|번째)?$", re.IGNORECASE)


def _validate_candidate_planning_response(raw: dict) -> str | None:
    candidates = raw.get("candidates")
    if not isinstance(candidates, list) or not (2 <= len(candidates) <= 3):
        return "candidates_count_invalid"
    seen_ids: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            return "candidate_not_object"
        candidate_id = candidate.get("candidate_id")
        if _blank(candidate_id) or candidate_id in seen_ids:
            return "candidate_id_missing_or_duplicate"
        seen_ids.add(candidate_id)
        for field in _REQUIRED_CANDIDATE_FIELDS:
            if _blank(candidate.get(field)):
                return f"missing_or_empty_field:{field}"
        if not isinstance(candidate.get("main_features"), list) or not candidate.get("main_features"):
            return "missing_or_empty_field:main_features"
    return None


def _validate_candidate_feasibility_response(raw: dict) -> str | None:
    reviews = raw.get("candidate_reviews")
    if not isinstance(reviews, list) or not reviews:
        return "candidate_reviews_missing"
    for review in reviews:
        if not isinstance(review, dict):
            return "candidate_review_not_object"
        if _blank(review.get("candidate_id")):
            return "missing_or_empty_field:candidate_id"
        if _blank(review.get("technical_approach")):
            return "missing_or_empty_field:technical_approach"
        if review.get("feasibility") not in _VALID_FEASIBILITY:
            return "invalid_feasibility_value"
    return None


def _validate_merge_analysis(merge_analysis: Any) -> str | None:
    """combine 해석 시 함께 요구되는 결합 분석 결과를 검증한다(요청: 공통 문제/공통 가치/
    결합 적합도/주 기능/보조 기능/충돌 지점/미확정 사항을 구조화된 필드로 강제)."""
    if not isinstance(merge_analysis, dict):
        return "merge_analysis_missing"
    if merge_analysis.get("fit") not in _VALID_MERGE_FIT:
        return "invalid_merge_analysis_fit"
    if _blank(merge_analysis.get("common_problem")) or _blank(merge_analysis.get("common_value")):
        return "missing_or_empty_field:merge_analysis_common_problem_or_value"
    for field in ("primary_features", "secondary_features", "conflicts", "open_questions"):
        if not isinstance(merge_analysis.get(field), list):
            return f"merge_analysis_{field}_not_list"
    return None


def _validate_candidate_selection_response(raw: dict) -> str | None:
    resolution = raw.get("resolution")
    if resolution not in _VALID_RESOLUTIONS:
        return "invalid_resolution"
    if resolution in ("combine", "recommend"):
        idea = raw.get("combined_idea")
        if not isinstance(idea, dict):
            return "combined_idea_missing"
        for field in _REQUIRED_IDEA_FIELDS:
            if _blank(idea.get(field)):
                return f"missing_or_empty_field:{field}"
    if resolution == "combine":
        problem = _validate_merge_analysis(raw.get("merge_analysis"))
        if problem is not None:
            return problem
    if resolution == "unclear" and _blank(raw.get("clarifying_question")):
        return "missing_or_empty_field:clarifying_question"
    if resolution == "select":
        ids = raw.get("selected_candidate_ids")
        if not isinstance(ids, list) or not ids or _blank(ids[0]):
            return "selected_candidate_ids_missing"
    return None


def _contest_query(state: IdeationConvState) -> str:
    notice = state.get("notice_and_criteria")
    if isinstance(notice, dict):
        return " ".join(str(v) for v in notice.values() if v)
    return str(notice or "")


def _merge_candidate_reviews(candidates: list[dict], reviews: list[dict]) -> list[dict]:
    """기획 전문가 후보(problem/target_user/solution 등)와 개발 전문가 검토 결과
    (required_data/technical_approach/feasibility 등)를 candidate_id 기준으로 병합한다.
    review가 없는 후보(개발 전문가가 누락했을 때의 방어적 처리)는 feasibility="medium",
    빈 배열/문자열로 채운다 — 병합 자체가 실패하지는 않는다(개별 리뷰 결측은 전체 재시도
    사유로 삼지 않는다, 최소 1개 이상 존재하면 되도록 검증 단계에서 이미 확인했다)."""
    review_by_id = {r.get("candidate_id"): r for r in reviews if isinstance(r, dict)}
    merged = []
    for candidate in candidates:
        review = review_by_id.get(candidate.get("candidate_id"), {})
        merged.append(
            {
                **candidate,
                "required_data": review.get("required_data") or [],
                "technical_approach": review.get("technical_approach") or "",
                "mvp_scope": review.get("mvp_scope") or "",
                "feasibility": review.get("feasibility") or "medium",
                "risks": review.get("risks") or [],
                "dev_notes": review.get("dev_notes"),
            }
        )
    return merged


def _normalize(text: str) -> str:
    return (text or "").strip()


def _is_regenerate_request(text: str) -> bool:
    normalized = _normalize(text)
    return any(keyword in normalized for keyword in _REGENERATE_KEYWORDS)


def _match_single_candidate(text: str, candidates: list[dict]) -> dict | None:
    """번호/후보 id/제목 정확 일치만 결정적으로 처리한다(요청: 단순 번호 선택은 코드로).
    그 외(복수 선택, 결합 의도, 수정 요청이 섞인 문장 등)는 None을 반환해 LLM 해석으로
    넘긴다."""
    normalized = _normalize(text)
    if not normalized or not candidates:
        return None
    match = _NUMERIC_SELECT_RE.match(normalized)
    if match:
        index = int(match.group(2)) - 1
        return candidates[index] if 0 <= index < len(candidates) else None
    for candidate in candidates:
        if normalized == str(candidate.get("candidate_id", "")):
            return candidate
    lowered = normalized.lower()
    for candidate in candidates:
        title = str(candidate.get("title", "")).strip().lower()
        if title and lowered == title:
            return candidate
    return None


def _find_candidate(candidates: list[dict], candidate_id: str | None) -> dict | None:
    if not candidate_id:
        return None
    for candidate in candidates:
        if candidate.get("candidate_id") == candidate_id:
            return candidate
    return None


def _resolve_selection(
    state: IdeationConvState,
    *,
    idea: dict,
    reason: str,
    source: str,
    source_ids: list[str],
    user_selection_message: str | None = None,
    source_candidates: list[dict] | None = None,
    merge_analysis: dict | None = None,
) -> dict[str, Any]:
    """선택/결합/추천이 확정된 아이디어를 refinement로 넘길 형태로 변환한다. 이후
    refinement 흐름(질문/의견/재질문/최종 종합)은 전혀 수정하지 않고 그대로 재사용한다
    (요청 4번 "discovery에서 선택된 아이디어도 동일한 refinement 흐름으로 발전").

    user_selection_message/source_candidates/merge_analysis(요청: 후보 결합 컨텍스트
    보존)는 state에 그대로 저장되어, 이후 refinement 질문 프롬프트가 "1번과 2번"이
    실제로 무엇이었는지를 conversation_context의 최근 메시지에 우연히 남아있는 것에
    기대지 않고 명시적으로 참조할 수 있게 한다(ideation_conv_nodes.py::
    _selection_context_for 참고). source는 이미 "select"/"combine"/"recommend" 중
    하나이므로 selection_intent 값으로 그대로 재사용한다."""
    idea = dict(idea)
    idea["source"] = source
    idea["source_candidate_ids"] = source_ids

    summary_message = _build_message(
        persona_id="ideation_facilitator",
        round_number=state["round"],
        message_type="summary",
        content=(
            f"선택된 아이디어: {idea.get('title', '')}\n"
            f"문제: {idea.get('problem', '')}\n"
            f"선택 이유: {reason}"
        ),
        referenced_message_ids=[],
        evidence=[],
    )
    title = idea.get("title", "") or ""
    problem = idea.get("problem", "") or ""
    initial_idea_text = f"{title} — {problem}".strip(" —") or None

    return {
        "messages": [summary_message],
        "selected_idea": idea,
        "selection_reason": reason,
        "user_idea": idea,
        "initial_idea": initial_idea_text,
        "phase": "planning_question",
        "selection_intent": source,
        "user_selection_message": user_selection_message,
        "source_candidates": source_candidates if source_candidates is not None else [],
        "merge_analysis": merge_analysis,
    }


def make_candidate_planning_node(
    llm_call: LLMCall,
    evidence_lookup: EvidenceLookup | None = None,
) -> Callable[[IdeationConvState], dict]:
    """기획 전문가가 공모전 분석 + 서로 다른 아이디어 후보 2~3개를 만드는 노드. 개발
    전문가의 실현 가능성 검토(candidate_feasibility)로 정지 없이 바로 이어진다(요청
    3-2/3-3 — 후보 제시 전까지는 사용자에게 정지 지점을 보이지 않는다)."""

    def node(state: IdeationConvState) -> dict:
        retrieved = evidence_lookup("planning_expert", _contest_query(state)) if evidence_lookup is not None else []
        previous_candidates = state.get("idea_candidates") or []
        regeneration_reason = None
        if previous_candidates:
            last_answer = _last_user_answer(state["messages"])
            regeneration_reason = (last_answer or {}).get("content")

        prompt = build_ideation_conv_candidate_planning_prompt(
            state["notice_and_criteria"], retrieved, previous_candidates, regeneration_reason
        )
        raw, ok, attempts = _safe_call_structured_json(
            llm_call, prompt, _validate_candidate_planning_response, "candidate_planning"
        )
        used = state.get("llm_calls_used", 0) + attempts
        if not ok:
            return {"phase": "failed", "failed_node": "candidate_planning", "llm_calls_used": used}

        return {
            "idea_candidates": raw["candidates"],
            "contest_analysis": raw.get("contest_analysis"),
            "llm_calls_used": used,
        }

    return node


def make_candidate_feasibility_node(
    llm_call: LLMCall,
    evidence_lookup: EvidenceLookup | None = None,
) -> Callable[[IdeationConvState], dict]:
    """개발 전문가가 기획 전문가의 후보들을 실현 가능성 관점에서 검토하고 병합해, 사용자에게
    선택 질문 하나를 던지고 멈춘다(awaiting_candidate_selection)."""

    def node(state: IdeationConvState) -> dict:
        candidates = state.get("idea_candidates") or []
        retrieved = evidence_lookup("dev_expert", _contest_query(state)) if evidence_lookup is not None else []
        prompt = build_ideation_conv_candidate_feasibility_prompt(state["notice_and_criteria"], candidates, retrieved)
        raw, ok, attempts = _safe_call_structured_json(
            llm_call, prompt, _validate_candidate_feasibility_response, "candidate_feasibility"
        )
        used = state.get("llm_calls_used", 0) + attempts
        if not ok:
            return {"phase": "failed", "failed_node": "candidate_feasibility", "llm_calls_used": used}

        merged = _merge_candidate_reviews(candidates, raw.get("candidate_reviews") or [])
        question_message = _build_message(
            persona_id="ideation_facilitator",
            round_number=state["round"],
            message_type="question",
            content=_SELECTION_QUESTION,
            referenced_message_ids=[],
            evidence=[],
        )
        update: dict[str, Any] = {
            "idea_candidates": merged,
            "messages": [question_message],
            "phase": "awaiting_candidate_selection",
            "llm_calls_used": used,
        }
        if not state.get("original_idea_candidates"):
            # 최초 생성일 때만 캡처한다 — 재추천으로 idea_candidates가 갱신돼도 이 값은
            # 그대로 남아 최종 결과의 "최초 생성 후보" 이력이 된다(요청 8번).
            update["original_idea_candidates"] = merged
        return update

    return node


def make_candidate_selection_node(
    llm_call: LLMCall,
    evidence_lookup: EvidenceLookup | None = None,
) -> Callable[[IdeationConvState], dict]:
    """사용자의 후보 선택/결합/재추천/전문가추천 요청을 처리한다. 단순 번호·제목 선택과
    재추천 키워드는 LLM 없이 코드가 결정적으로 처리하고, 결합·전문가추천·모호한 답변만
    LLM을 호출한다(요청: 단순 선택은 코드로, 자연어 결합/수정 요청에만 LLM)."""

    def node(state: IdeationConvState) -> dict:
        candidates = state.get("idea_candidates") or []
        last_answer = _last_user_answer(state["messages"])
        text = _normalize((last_answer or {}).get("content", ""))

        matched = _match_single_candidate(text, candidates)
        if matched is not None:
            return _resolve_selection(
                state,
                idea=matched,
                reason=f"사용자가 '{matched.get('title') or matched.get('candidate_id')}'를 선택했습니다.",
                source="select",
                source_ids=[matched.get("candidate_id")],
                user_selection_message=text,
                source_candidates=[matched],
            )

        if _is_regenerate_request(text):
            regen_count = state.get("candidate_regeneration_count", 0)
            if regen_count >= _MAX_CANDIDATE_REGENERATIONS:
                notice = _build_message(
                    persona_id="ideation_facilitator",
                    round_number=state["round"],
                    message_type="summary",
                    content=(
                        f"후보 재추천은 최대 {_MAX_CANDIDATE_REGENERATIONS}회까지 가능합니다. "
                        "현재 제시된 후보 중에서 선택하거나 '전문가 추천'을 요청해 주세요."
                    ),
                    referenced_message_ids=[],
                    evidence=[],
                )
                return {"messages": [notice], "phase": "awaiting_candidate_selection"}
            return {
                "phase": "candidate_generation",
                "candidate_regeneration_count": regen_count + 1,
            }

        prompt = build_ideation_conv_candidate_selection_prompt(state["notice_and_criteria"], candidates, text)
        raw, ok, attempts = _safe_call_structured_json(
            llm_call, prompt, _validate_candidate_selection_response, "candidate_selection"
        )
        used = state.get("llm_calls_used", 0) + attempts
        if not ok:
            return {"phase": "failed", "failed_node": "candidate_selection", "llm_calls_used": used}

        resolution = raw["resolution"]
        if resolution == "unclear":
            question_message = _build_message(
                persona_id="ideation_facilitator",
                round_number=state["round"],
                message_type="question",
                content=raw["clarifying_question"],
                referenced_message_ids=[],
                evidence=[],
            )
            return {"messages": [question_message], "phase": "awaiting_candidate_selection", "llm_calls_used": used}

        source_ids = [i for i in (raw.get("selected_candidate_ids") or []) if not _blank(i)]
        source_candidates_full = [c for c in (_find_candidate(candidates, sid) for sid in source_ids) if c is not None]

        if resolution == "select":
            idea = _find_candidate(candidates, source_ids[0] if source_ids else None)
            if idea is None:
                # 방어적 처리 — LLM이 select를 골랐지만 candidate_id가 실제 후보와 매칭되지
                # 않는 경우(모델 오류). 조용히 잘못된 후보로 진행하지 않고 다시 묻는다.
                question_message = _build_message(
                    persona_id="ideation_facilitator",
                    round_number=state["round"],
                    message_type="question",
                    content="선택하신 후보를 특정할 수 없습니다. 후보 번호나 제목을 다시 알려 주세요.",
                    referenced_message_ids=[],
                    evidence=[],
                )
                return {
                    "messages": [question_message],
                    "phase": "awaiting_candidate_selection",
                    "llm_calls_used": used,
                }
            result = _resolve_selection(
                state,
                idea=idea,
                reason=raw.get("selection_reason", ""),
                source="select",
                source_ids=source_ids,
                user_selection_message=text,
                source_candidates=[idea],
            )
        elif resolution == "combine":
            merge_analysis = raw.get("merge_analysis") or {}
            if merge_analysis.get("fit") == "low":
                # 요청 5번 — 결합 적합도가 낮으면 바로 selected_idea를 확정하지 않는다.
                # 사용자가 선택한 두 후보가 무엇인지, 목적이 어떻게 다른지, 결합 시 발생하는
                # 범위/정체성 문제를 설명하고 주 방향을 물은 뒤 여전히 후보 선택 대기 상태로
                # 남는다 — 다만 이번 요청에서 파악한 컨텍스트(source_candidates/merge_analysis/
                # selection_intent/user_selection_message)는 잃지 않도록 state에 보존한다.
                candidate_lines = "\n".join(
                    f"{i + 1}. {c.get('title', '')} — {c.get('problem', '')}"
                    for i, c in enumerate(source_candidates_full)
                )
                low_fit_content = (
                    f"[선택한 후보]\n{candidate_lines or '(후보를 특정할 수 없습니다)'}\n\n"
                    f"[목적 차이]\n{merge_analysis.get('common_problem') or '두 후보가 공유하는 문제를 찾기 어렵습니다.'} "
                    "두 후보는 서로 다른 목표를 지향하고 있어, 단순히 합치면 범위가 넓어지거나 "
                    "제품의 정체성이 흐려질 수 있습니다.\n\n"
                    f"[결합 시 발생하는 문제]\n{_bullets(merge_analysis.get('conflicts'))}\n\n"
                    "[질문]\n두 후보 중 어느 쪽을 주 방향으로 삼고, 다른 쪽을 보조 요소로만 "
                    "반영할까요?"
                )
                message = _build_message(
                    persona_id="ideation_facilitator",
                    round_number=state["round"],
                    message_type="question",
                    content=low_fit_content,
                    referenced_message_ids=[],
                    evidence=[],
                )
                return {
                    "messages": [message],
                    "phase": "awaiting_candidate_selection",
                    "selection_intent": "combine",
                    "user_selection_message": text,
                    "source_candidates": source_candidates_full,
                    "merge_analysis": merge_analysis,
                    "llm_calls_used": used,
                }
            result = _resolve_selection(
                state,
                idea=raw["combined_idea"],
                reason=raw.get("selection_reason", ""),
                source="combine",
                source_ids=source_ids,
                user_selection_message=text,
                source_candidates=source_candidates_full,
                merge_analysis=merge_analysis,
            )
        else:  # resolution == "recommend"
            result = _resolve_selection(
                state,
                idea=raw["combined_idea"],
                reason=raw.get("selection_reason", ""),
                source="recommend",
                source_ids=source_ids,
                user_selection_message=text,
                source_candidates=source_candidates_full,
            )

        result["llm_calls_used"] = used
        assumptions = [a for a in (raw.get("unverified_assumptions") or []) if a and a not in state["unresolved_issues"]]
        if assumptions:
            result["unresolved_issues"] = list(state["unresolved_issues"]) + assumptions
        return result

    return node
