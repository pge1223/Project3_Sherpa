# 작성자: 용준/Claude(2026-07-20)
# 목적: 대화형 아이디어 발전 회의(ideation-conversation) LangGraph 노드.
#       배치형 ideation_nodes.py와 노드 "내용"은 비슷하지만(페르소나 프롬프트 조립, LLM
#       호출, JSON 정규화), 각 노드가 "질문 하나를 던지고 즉시 멈춘다"는 점이 근본적으로
#       다르다 — 배치형은 위원 4명이 한 그래프 실행 안에서 순서대로 다 말하고 나서야
#       facilitator가 사용자 질문 여부를 판단하지만, 이 모듈의 노드들은 그 자체가 "정지
#       지점"이라서 각 노드가 끝나면 그래프는 항상 END로 간다(정지는 그래프 조립부
#       ideation_conv_build.py가 아니라 여기 각 노드가 반환하는 phase가 결정한다).
# import: prompts.build_ideation_conv_*(형제 패키지), 같은 패키지의 ideation_conv_state/llm,
#         _safe_call_json은 배치형 노드(ideation_nodes.py)의 것을 그대로 재사용한다(LLM 호출
#         실패 시 재시도 1회 후 폴백하는 정책을 새로 만들지 않고 통일하기 위함).

from __future__ import annotations

import logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from prompts import (
    build_ideation_conv_canvas_update_prompt,
    build_ideation_conv_discussion_facilitator_prompt,
    build_ideation_conv_discussion_prompt,
    build_ideation_conv_expert_delegation_facilitator_prompt,
    build_ideation_conv_expert_delegation_prompt,
    build_ideation_conv_expert_delegation_review_prompt,
    build_ideation_conv_question_prompt,
    build_ideation_conv_sufficiency_prompt,
    build_ideation_conv_synthesis_prompt,
    get_persona_card,
)

from .ideation_conv_state import (
    TOPIC_PRIORITY,
    ConvMessage,
    DiscussionRoundRecord,
    IdeationCancelled,
    IdeationConvState,
    remaining_topics_for,
)
from .ideation_nodes import EvidenceLookup, _safe_call_json, call_evidence_lookup
from .ideation_trace import sanitize_preview, trace_event
from .llm import LLMCall, parse_json_response

logger = logging.getLogger(__name__)

# 용준/Claude(2026-07-22, 요청: RAG 근거 실제 활용 강화) — EvidenceLookup(ai/meeting/graph/
# ideation_nodes.py)과 같은 이유로, claim-evidence 연결 검증도 ai/meeting이 ai.rag를 직접
# import하지 않는다(ai/rag/tests/test_meeting_evidence_service.py::TestScopeBoundary가 이
# 경계를 강제한다 — ai/meeting/graph는 ai.rag를 몰라야 하고, 실제 검색/근거 판정 구현은
# 항상 호출부(backend)가 주입한다). ClaimGroundingFn은 claims(LLM이 반환한 리스트)와
# retrieved_evidence(이번 턴 검색 결과)를 받아 ai.rag.evidence_linking.claim_grounding.
# ground_claims()와 같은 모양의 dict(claims/linked_evidence_refs/unsupported_claims/
# supported_claim_count/unsupported_claim_count/missing_information/evidence_status/
# prompt_guard/allow_definitive_judgment)를 반환해야 한다 — 이 파일은 그 결과의 "모양"만
# 알고 실제 관련성 판정 로직은 모른다. persona_id를 함께 넘겨 역할별 관련성 키워드(기획/개발)
# 적용은 주입된 함수(호출부)가 알아서 하게 한다.
ClaimGroundingFn = Callable[[str, Any, list[dict]], dict]

# 용준/Claude(2026-07-23, Phase 1 "Shadow Deterministic Evidence Planner") — evidence_lookup/
# ground_claims와 같은 경계 원칙: 실제 규칙 기반 evidence 선택 구현(ai/rag/orchestration/
# ideation_evidence_planner.py::build_evidence_plan)은 backend가 주입하고, 이 파일은 그
# 결과가 plain dict(EvidencePlan 모양)라는 것만 안다. persona_id/effective_issue(issue_id/
# title/query)/retrieved_evidence(이번 턴 검색 결과)/runtime_scope(session_id/
# selected_candidate_document_id)/shadow_history(같은 speaker/issue의 이전 shadow 선택
# 이력)를 keyword-only로 받는다 — 키워드 전용으로 둔 이유는 이 콜러블이 신규 도입이라
# 위치 인자 순서에 의존할 legacy 호출자가 없기 때문이다. Phase 1에서는 이 결과가 prompt/
# claims/grounding/routing 어디에도 쓰이지 않고 trace 로그로만 기록된다.
EvidencePlanningFn = Callable[..., dict]

# 같은 speaker/issue 조합("persona_id:issue_id")별로 보관하는 shadow 선택 이력 최대 개수 —
# 무제한 누적을 막는다(요청: 최소 정보만 유지).
_SHADOW_HISTORY_KEEP = 20

_EMPTY_GROUNDING: dict = {
    "claims": [],
    "linked_evidence_refs": [],
    # 용준/Claude(2026-07-23, 요청: IDEATION_EVIDENCE_LINKED 로그 매핑 수정) — ai.rag.
    # evidence_linking.claim_grounding.ClaimGroundingResult와 모양을 맞춘다.
    "claim_evidence_links": [],
    "unsupported_claims": [],
    "supported_claim_count": 0,
    "unsupported_claim_count": 0,
    "accepted_claim_count": 0,
    "grounded_claim_count": 0,
    "expert_judgment_count": 0,
    "linked_evidence_count": 0,
    "missing_information": [],
    "evidence_status": "no_evidence_available",
    "prompt_guard": "",
    "allow_definitive_judgment": False,
}


def _has_hard_grounding_failure(grounding: dict) -> bool:
    """document_fact 주장이 있는데 전부 unsupported면 재생성 대상이다 — ai.rag.
    evidence_linking.claim_grounding.has_hard_grounding_failure와 동일한 판정을 dict
    형태(주입된 함수의 반환값)에 대해 그대로 수행한다(로직 자체는 ai.rag 쪽에 있고, 여기서는
    그 결과 dict의 구조만 본다)."""
    document_fact_claims = [c for c in grounding["claims"] if c.get("claim_type") == "document_fact"]
    if not document_fact_claims:
        return False
    unsupported_ids = {c["claim_id"] for c in grounding["unsupported_claims"]}
    return all(c.get("claim_id") in unsupported_ids for c in document_fact_claims)

_CANVAS_TEXT_FIELDS = ("problem", "target_user", "core_value", "solution", "differentiation", "contest_fit")
_VALID_CANVAS_FEASIBILITY = {"high", "medium", "low", ""}
_MAX_CANVAS_RISKS = 4

_VALID_DISCUSSION_STANCES = {"동의", "조건부_동의", "반박", "보완", "대안_제시"}
_EXPERT_ROLE_LABELS = {
    "planning_expert": "기획 위원",
    "dev_expert": "개발 위원",
    "ideation_facilitator": "진행자",
    "user": "사용자",
}
_SELF_REFERENCE_PATTERNS = {
    "planning_expert": re.compile(r"기획\s*(?:전문가|위원|측|자)(?:가|이|은|는|의|에서|에게|대로)?"),
    "dev_expert": re.compile(r"개발\s*(?:전문가|위원|측|자)(?:가|이|은|는|의|에서|에게|대로)?"),
}
_EMPTY_MEETING_PHRASES = (
    "좋은 의견입니다",
    "중요성에 동의",
    "중요한 부분입니다",
    "구체적인 계획이 필요",
    "구체적인 고민이 필요",
    "추가적인 논의가 필요",
    "추가 논의가 필요",
)
# 용준/Claude(2026-07-21): 질문 노드가 반환하는 expected_answer_type의 허용값. sufficiency
# 판정이 "답변 충분성"(방금 질문에 답했는가)과 "아이디어 완성도"(전체적으로 충분히
# 구체적인가)를 혼동하지 않도록 질문의 성격을 알려주는 보조 정보다 — preference/selection은
# 하나를 명확히 고르기만 해도 충분하다고 판정해야 한다(ideation_conv_sufficiency.txt 참고).
_VALID_EXPECTED_ANSWER_TYPES = {"preference", "selection", "definition", "constraint", "evidence", "specification"}

# 용준/Claude(2026-07-21): 사용자 메시지 3분류 — "용어가 무슨 뜻인가요?" 같은 설명 요청을
# 답변 불충분으로 오판해 같은 질문을 반복하지 않도록, sufficiency 판정을 이진(충분/불충분)이
# 아니라 3분류로 바꾼다.
#   - answer: 질문에 실제로 답했다 -> 기존과 동일하게 다음 단계로 진행.
#   - clarification_request: 용어 설명/예시/선택지를 요청했다 -> 재질문 카운터를 늘리지 않고
#     설명 + 선택지를 먼저 준 뒤 같은 핵심 질문을 더 쉽게 다시 던진다.
#   - insufficient_answer: 회피/모순/미선택 등 실제로 불충분한 답이다 -> 기존 재질문 로직
#     그대로(카운터 증가, 상한 도달 시 강제 진행).
#   - expert_delegation(용준/Claude(2026-07-21), 요청: "모르겠다" UX 개선): 사용자가 질문에
#     답하는 대신 전문가 판단에 명시적으로 맡겼다("잘 모르겠어", "전문가가 정해주세요" 등) ->
#     같은 질문을 반복하지 않고, 담당 전문가가 자신의 평가 범위 안에서 합리적인 방향을
#     "임시 가정"으로 제안한 뒤 다음 단계로 진행한다(ideation_conv_run.py::_delegate_to_expert).
_VALID_ANSWER_TYPES = {"answer", "clarification_request", "insufficient_answer", "expert_delegation"}

# 용준/Claude(2026-07-21, 요청: "모르겠다" UX 개선): 명시적인 위임 표현은 작은 모델이 잘못
# 분류하지 않도록 LLM 판정(judge_answer_sufficiency) 앞에서 결정적 규칙으로 먼저 감지한다
# (요청 사항 그대로) — 매칭되면 sufficiency LLM 호출 자체를 건너뛴다. "MVP가 무슨 뜻인지
# 모르겠어요"처럼 용어 설명을 요청하는 clarification_request와 "모르겠"이 겹치므로,
# _TERM_QUESTION_MARKERS(용어 질문 표지)가 있으면 절대 위임으로 보지 않는다 — 그 경우는
# 기존 LLM 판정이 clarification_request로 분류하도록 그대로 둔다.
_TERM_QUESTION_MARKERS = (
    "무슨 뜻",
    "무슨 의미",
    "뜻인가요",
    "뜻이에요",
    "뜻이 뭐",
    "뭔가요",
    "의미인가요",
    "무엇인가요",
    "뭔지",
    "뭐에요",
    "뭐예요",
)

_EXPERT_DELEGATION_PATTERNS = (
    re.compile(r"^(음+[.,]?\s*|그냥\s*|아+\s*)*(잘\s*)?모르겠(어|어요|습니다|네요|어서)[.!]*$"),
    re.compile(r"생각해\s*본\s*적\s*(이\s*)?없"),
    re.compile(r"감(이|이가)?\s*안\s*(와|옵니다|와요)"),
    re.compile(r"전문가.{0,6}(정해|추천|판단)"),
    re.compile(r"알아서\s*(제안|정해|골라)"),
    re.compile(r"추천해\s*(주세요|줘|주실래요|주시면)"),
    re.compile(r"구체적으로\s*(설명하기|말하기|설명을?)\s*(어려워요|못\s*하겠)"),
    # "어떤 방향이 좋은지 모르겠어요" / "어떤 기술이 좋은지 모르겠어요"처럼 "어떤 (무엇)이
    # 좋을지/좋은지 모르겠다" 형태를 폭넓게 잡는다(요청 예시 그대로 — 기획/개발 질문 모두
    # 이 형태로 위임할 수 있다).
    re.compile(r"어떤\s*[가-힣]{0,12}이?\s*좋(을지|은지)\s*모르겠"),
)

# 짧고 명확한 위임 발화만 결정적으로 처리한다 — 사용자가 위임 표현과 함께 실제 내용을
# 덧붙인 긴 문장("생각해 본 적 없어요, 그런데 아마도 ~일 것 같아요")까지 무조건 위임으로
# 단정하면 실제 답변을 놓칠 위험이 있으므로, 이런 혼합 문장은 길이 제한을 넘겨 LLM
# 판정(judge_answer_sufficiency)으로 넘긴다.
_EXPERT_DELEGATION_MAX_CHARS = 30


def is_expert_delegation_request(text: str) -> bool:
    """사용자가 pending_question에 답하는 대신 전문가의 판단에 맡기겠다는 의도를 명시적으로
    밝혔는지 결정적 규칙으로 감지한다."""
    normalized = (text or "").strip()
    if not normalized or len(normalized) > _EXPERT_DELEGATION_MAX_CHARS:
        return False
    if any(marker in normalized for marker in _TERM_QUESTION_MARKERS):
        return False
    return any(pattern.search(normalized) for pattern in _EXPERT_DELEGATION_PATTERNS)

# 용준/Claude(2026-07-21, 질문 품질 개선): 실제 사용자 테스트에서 전문가 의견이 너무
# 길고 반복적이라는 문제가 확인됐다(요청 8번) — 구조화 응답 검증 단계에서 분량을 강제한다.
# 문자열을 임의로 잘라내지 않는다("의미가 잘릴 수 있으므로 단순 문자열 강제 절단은 피하세요")
# — 초과하면 _safe_call_structured_json의 기존 재시도(최대 1회) 정책을 그대로 타고, 재시도
# 후에도 초과하면 다른 구조화 검증 실패와 동일하게 phase="failed"로 처리한다(이 코드베이스
# 전체가 구조화 응답 검증 실패에 일관되게 적용하는 정책 — 후보 생성 검증 등과 동일).
_MAX_JUDGMENT_CHARS = 200
_MAX_REASON_CHARS = 400
_MAX_SUGGESTION_CHARS = 300
_MAX_CONFIRMED_ITEMS = 3
_MAX_UNCONFIRMED_ITEMS = 3
# 용준/Claude(2026-07-21, 요청: 전문가 라운드테이블 전환) — interim_conclusion(임시 결론)은
# 매 발언마다 필수다(요청 4번: "현재 임시 결론"). 다른 짧은 필드와 같은 상한을 둔다.
_MAX_INTERIM_CONCLUSION_CHARS = 200
# 용준/Claude(2026-07-22, 요청: 보고서형 메시지 → 자연스러운 회의 발화 전환) — 화면에 실제로
# 보이는 spoken_text의 분량 상한. 위원 발언/질문/위임 제안·검토는 1~3문장을 기준으로 300자,
# 진행자(라운드 정리·위임 최종 권고)는 1~2문장을 기준으로 더 짧은 200자를 둔다.
_MAX_SPOKEN_TEXT_CHARS = 300
_MAX_FACILITATOR_SPOKEN_TEXT_CHARS = 200

_STANCE_TO_MESSAGE_TYPE = {
    "동의": "agreement",
    "조건부_동의": "agreement",
    "반박": "disagreement",
}
_RECENT_MESSAGES_LIMIT = 8

# awaiting_planning_answer/awaiting_developer_answer 중 사용자가 방금 답한 질문을 던진
# 전문가가 누구인지 phase만으로 판별한다(ideation_conv_run.py의 answer_sufficiency 게이트에서
# 사용 — 요청 3번 재질문 조건).
PHASE_TO_PENDING_PERSONA = {
    "awaiting_planning_answer": "planning_expert",
    "awaiting_developer_answer": "dev_expert",
}


def _blank(value: Any) -> bool:
    return not isinstance(value, str) or not value.strip()


def _safe_call_structured_json(
    llm_call: LLMCall,
    prompt: str,
    validate: Callable[[dict], str | None],
    node_name: str,
) -> tuple[dict | None, bool, int]:
    """JSON 파싱 + 스키마(필수 필드 비어있지 않음) 검증을 함께, 최대 2회(최초 1회 + 재시도
    1회) 시도한다 — 요청 7번 "구조화 응답이 유효하지 않으면 최대 1회 재시도" +
    "필수 문자열이 없거나 공백이면 성공으로 처리하지 않음". validate(raw)는 문제가 있으면
    이유 문자열을, 없으면 None을 반환해야 한다.

    반환값은 (raw_또는_None, 성공여부, 실제 시도 횟수) — 세 번째 값은 호출부가
    llm_calls_used를 정확히 누적하기 위한 것이다(재시도가 실제로 LLM을 한 번 더 호출하기
    때문). 실패하면 warning 로그를 남기되, 이전에 발생했던 "빈 카드" 문제를 재현하지
    않도록 실패 사유(필드명 수준)만 남기고 프롬프트 원문·LLM 원응답·사용자 입력은 로그에
    포함하지 않는다."""
    last_reason = "unknown"
    for attempt in range(1, 3):
        try:
            raw = parse_json_response(llm_call(prompt))
        except (ValueError, KeyError, TypeError):
            last_reason = "json_parse_failed"
            trace_event(
                "IDEATION_STRUCTURED_RESPONSE_VALIDATION_FAILED",
                node=node_name,
                attempt=attempt,
                reason=last_reason,
                will_retry=attempt < 2,
            )
            discard = getattr(llm_call, "discard_streamed_prompt", None)
            if callable(discard):
                discard(prompt, last_reason)
            continue
        problem = validate(raw)
        if problem is None:
            return raw, True, attempt
        last_reason = problem
        trace_event(
            "IDEATION_STRUCTURED_RESPONSE_VALIDATION_FAILED",
            node=node_name,
            attempt=attempt,
            reason=last_reason,
            will_retry=attempt < 2,
        )
        discard = getattr(llm_call, "discard_streamed_prompt", None)
        if callable(discard):
            discard(prompt, last_reason)
    logger.warning("[%s] 구조화 응답 검증 실패 reason=%s", node_name, last_reason)
    return None, False, 2


def _safe_discussion_fallback(
    *,
    persona_id: str,
    state: IdeationConvState,
    discussion_stage: str,
    responding_to_message_id: str | None,
    responding_to_content: str | None,
) -> dict:
    """두 번의 구조화 응답 검증이 모두 실패했을 때 저장할 서버 생성 발언.

    문서 내용을 추측하지 않는 expert_judgment만 만들고 기존 discussion 후처리와 라우터를
    그대로 통과시킨다. 따라서 일시적인 LLM 형식 오류가 회의 전체를 failed로 만들지 않는다.
    """
    issue = resolve_effective_issue(state, persona_id)
    issue_id = issue["issue_id"]
    issue_title = issue["title"]
    counterpart = _DISCUSSION_COUNTERPART.get(persona_id, "ideation_facilitator")
    spoken_text = (
        f"현재 응답 형식을 안정적으로 확인하지 못해 {issue_title}에 관한 문서 사실을 확정하기 어렵습니다. "
        "검색 자료와 세부 조건을 추가로 확인한 뒤 판단을 보완해야 합니다."
    )
    responding_to = (
        "앞선 의견의 세부 근거를 추가로 확인해야 합니다."
        if discussion_stage == "response" and responding_to_content
        else None
    )
    return {
        "stance": "보완",
        "judgment": f"{issue_title}에 대한 추가 확인이 필요합니다.",
        "reason": "두 차례 생성된 구조화 응답이 검증을 통과하지 않아 문서 사실을 안전하게 확정할 수 없습니다.",
        "suggestion": "검색 자료와 사용자 조건을 다시 확인한 뒤 구체적인 판단을 이어갑니다.",
        "interim_conclusion": "현재 단계에서는 문서 사실을 단정하지 않고 추가 확인이 필요하다고 정리합니다.",
        "spoken_text": spoken_text,
        "responding_to": responding_to,
        "agreement": "추가 검토가 필요하다는 점은 수용합니다." if responding_to else None,
        "concern": "현재 자료만으로 구체적인 사실을 단정할 수 없습니다." if responding_to else None,
        "revision": None,
        "confirmed": [],
        "unconfirmed": [f"{issue_title} 관련 세부 근거"],
        "referenced_message_ids": [responding_to_message_id] if responding_to_message_id else [],
        "claims": [
            {
                "claim_id": "safe_fallback_judgment",
                "text": f"{issue_title}에 대한 추가 확인이 필요합니다.",
                "claim_type": "expert_judgment",
                "evidence_refs": [],
            }
        ],
        "next_action": None,
        "active_issue_id": issue_id,
        "active_issue_title": issue_title,
        "new_information": ["구조화 응답 검증 실패로 문서 사실 확정을 보류함"],
        "proposal": None,
        "changed_position": False,
        "needs_counterpart_response": True,
        "recommended_next_speaker": counterpart,
        "issue_resolved": False,
        "needs_user_input": False,
        "user_question": None,
        "safe_fallback": True,
        "safe_fallback_reason": "structured_response_validation_failed_twice",
    }


def _safe_fallback_spoken_text(grounding: dict) -> str:
    """검증에 최종 실패했을 때 화면에 노출할 안전한 발언(요청 7번). 근거 없는 사실을 확정
    표현으로 내보내는 대신, 확인이 필요한 항목을 있는 그대로 말한다."""
    missing = [m for m in grounding["missing_information"] if m][:2]
    if missing:
        detail = " · ".join(missing)
        text = f"현재 제공된 자료에서는 {detail} 부분을 문서로 확인하기 어렵습니다. 추가 확인이 필요합니다."
    else:
        text = "현재 제공된 자료에서는 이 주장을 문서 근거로 확인하기 어렵습니다. 추가 확인이 필요합니다."
    return text[:_MAX_SPOKEN_TEXT_CHARS]


def _ground_and_finalize_claims(
    *,
    persona_id: str,
    raw: dict,
    retrieved: list[dict],
    prompt: str,
    llm_call: LLMCall,
    validate: Callable[[dict], str | None],
    used: int,
    ground_claims_fn: ClaimGroundingFn | None,
) -> tuple[dict, dict, int]:
    """구조화 검증(_safe_call_structured_json)을 통과한 raw 응답의 claims를 실제 검색 근거와
    대조 검증한다(요청: 최종 발언의 주장과 실제 청크가 연결되고 관련성 검증을 통과해야만
    RAG 활용 성공으로 판단). document_fact 주장이 전부 근거 연결에 실패하면 실패 사유를
    프롬프트에 덧붙여 딱 한 번만 재생성한다 — 무한 재시도는 하지 않는다(기존
    _safe_call_structured_json의 재시도 1회 정책과는 별개 축이다: 그쪽은 "필수 필드
    누락"을, 이쪽은 "구조는 유효했지만 근거 연결에 실패"를 다룬다). 재시도 후에도 실패하면
    spoken_text를 안전한 표현으로 교체한 뒤 그대로 진행한다(발언 자체를 폐기하지 않는다 —
    요청: 회의가 중단되지 않아야 한다).

    ground_claims_fn이 없으면(use_rag 미사용 세션 등) 검증을 건너뛰고 빈 grounding 결과를
    돌려준다 — retrieved가 없을 때 evidence_lookup을 건너뛰는 것과 같은 원칙이다."""
    if ground_claims_fn is None:
        return raw, dict(_EMPTY_GROUNDING), used

    started = time.perf_counter()
    trace_event(
        "IDEATION_CLAIM_GROUNDING_START",
        speaker=persona_id,
        claim_count=len(raw.get("claims") or []),
        retrieved_evidence_count=len(retrieved),
        injected_evidence_count=len(retrieved),
    )
    grounding = ground_claims_fn(persona_id, raw.get("claims"), retrieved)

    if _has_hard_grounding_failure(grounding):
        reasons = sorted({c["reason"] for c in grounding["unsupported_claims"]})
        trace_event("IDEATION_GROUNDING_RETRY", speaker=persona_id, retry_count=1, reasons=reasons)
        # 용준/Claude(2026-07-23, 요청: grounding 재시도 프롬프트의 ref 계약 오류 수정) —
        # 이 안내문은 예전에 evidence_refs가 chunk_id(해시)를 직접 담던 시절 문구가 그대로
        # 남아 있었다. call_evidence_lookup이 각 근거에 짧은 순번 참조("ref": "E1")를 부여한
        # 뒤부터는 evidence_refs에 chunk_id를 쓰라고 재시도 안내가 말하면 프롬프트 본문의
        # [근거 인용 규칙](ref만 사용)과 재시도 안내가 서로 다른 지시를 하게 된다 — 재시도
        # 안내도 반드시 ref 계약으로 통일한다. ref -> 실제 chunk_id 변환은 항상 서버의
        # ground_claims가 담당하고 LLM은 절대 chunk_id를 직접 다루지 않는다.
        retry_note = (
            "\n\n[근거 연결 재시도 안내] 방금 응답의 claims 중 document_fact로 표시한 주장이 "
            "retrieved_evidence의 실제 ref와 연결되지 않았습니다(사유: "
            + ", ".join(reasons)
            + "). 존재하지 않는 ref를 인용했거나, 인용한 근거가 그 주장과 무관하거나, "
            "evidence_refs가 비어 있었습니다. evidence_refs에는 retrieved_evidence 각 항목의 "
            "\"ref\" 필드 값(예: \"E1\", \"E2\")만 그대로 쓰고, chunk_id(긴 해시 문자열)는 "
            "직접 쓰지 마세요 — ref와 실제 chunk_id 사이의 변환은 서버가 처리합니다. "
            "retrieved_evidence에 실제로 있는 ref만 evidence_refs에 넣고, 문서에서 확인할 수 "
            "없는 내용은 claim_type을 expert_judgment로 바꾸거나 claims에서 제외하세요."
        )
        try:
            retry_raw = parse_json_response(llm_call(prompt + retry_note))
        except (ValueError, KeyError, TypeError):
            retry_raw = None
        if retry_raw is not None and validate(retry_raw) is None:
            used += 1
            raw = retry_raw
            grounding = ground_claims_fn(persona_id, raw.get("claims"), retrieved)

    if _has_hard_grounding_failure(grounding):
        raw = dict(raw)
        raw["spoken_text"] = _safe_fallback_spoken_text(grounding)

    trace_event(
        "IDEATION_CLAIM_GROUNDING_RESULT",
        speaker=persona_id,
        claim_count=len(grounding["claims"]),
        supported_claim_count=grounding["supported_claim_count"],
        unsupported_claim_count=grounding["unsupported_claim_count"],
        # 용준/Claude(2026-07-22, 요청: claim 통계 의미 분리) — supported_claim_count(기존
        # 필드, 호환 유지)와 별도로 "실제 문서 근거로 검증됨(grounded)"과 "근거 없이 허용된
        # 전문가 판단(expert_judgment)"을 분리해서 남긴다. linked_evidence_count=0인데
        # supported/accepted_claim_count>0인 것만 보고 "근거를 썼다"고 오인하지 않도록 한다.
        accepted_claim_count=grounding["accepted_claim_count"],
        grounded_claim_count=grounding["grounded_claim_count"],
        expert_judgment_count=grounding["expert_judgment_count"],
        linked_evidence_count=grounding["linked_evidence_count"],
        evidence_status=grounding["evidence_status"],
        missing_information=grounding["missing_information"],
        unsupported_reasons=[c["reason"] for c in grounding["unsupported_claims"]],
        elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
    )
    # 용준/Claude(2026-07-23, 요청: IDEATION_EVIDENCE_LINKED 로그 매핑 수정) — claim이
    # evidence_refs에 담는 값은 LLM이 인용한 ref("E1")이고, grounding["linked_evidence_refs"]는
    # 항상 실제 chunk_id다. 두 값 공간이 다르므로 "ref in linked_evidence_refs" 직접 비교는
    # (ref와 chunk_id가 우연히 같은 레거시 fixture를 빼면) 사실상 항상 실패했다 — 이제
    # ground_claims가 claim 단위로 짝지어 반환하는 claim_evidence_links(ref, chunk_id 쌍)를
    # 그대로 로그에 옮긴다. 구버전 ground_claims_fn(이 필드가 없는 테스트 더블 등)이 주입된
    # 경우를 위해 없으면 빈 리스트로 안전하게 처리한다.
    for link in grounding.get("claim_evidence_links") or []:
        trace_event(
            "IDEATION_EVIDENCE_LINKED",
            speaker=persona_id,
            claim_id=link["claim_id"],
            evidence_refs=link["evidence_refs"],
            chunk_ids=link["chunk_ids"],
        )
    return raw, grounding, used


def _make_validate_question_response(
    resolved_topics: list[str], roadmap_allowed: bool, require_combine_structure: bool = False
) -> Callable[[dict], str | None]:
    """질문 노드 응답 검증기를 만든다(요청: 질문 주제 구조화). resolved_topics/roadmap_allowed는
    이번 호출 시점의 state에서 계산된 값을 클로저로 고정한다 — 이 두 값 자체는 검증 중에
    바뀌지 않는다(같은 호출 안에서의 재시도 1회 동안은 동일한 상태를 기준으로 판정해야
    일관적이다).

    질문 노드가 반환한 question_topic이 다음 중 하나라도 해당하면 무효(재시도 유발)다 —
    "구조화 응답 실패"와 동일하게 취급해 phase="failed"로 이어질 수 있는 것은 다른 구조화
    검증과 같은 정책이다.
      - 허용되지 않은 값이거나 아예 없다(요청 10번: question_topic 누락/허용되지 않은 값 처리).
      - 이미 resolved_topics에 있는 주제다(요청 9번: 이미 해결된 주제를 다시 묻지 않는다 —
        프롬프트 규칙만으로는 보장이 안 되므로 코드로 한 번 더 막는다).
      - "roadmap"인데 roadmap_allowed=False다(요청: 선행 주제 미확인 시 roadmap 질문 금지 —
        이 검증이 그 강제의 최종 방어선이다. 1차 방어선은 애초에 프롬프트에 remaining_topics
        에서 roadmap을 아예 제외해 넘기는 것이다).

    require_combine_structure=True(용준/Claude(2026-07-21, 후보 결합 컨텍스트 보존)면 이번
    호출이 "후보 결합 직후 첫 전문가 메시지"다(요청 6번) — user_selection_summary/proposal
    필드도 비어있지 않아야 한다(_compose_question_content가 이 값들로 [사용자 선택 반영]/
    [제안] 섹션을 만든다)."""
    resolved_set = set(resolved_topics)

    def _validate(raw: dict) -> str | None:
        topic = raw.get("question_topic")
        if topic not in TOPIC_PRIORITY:
            return "invalid_or_missing_question_topic"
        if topic in resolved_set:
            return "question_topic_already_resolved"
        if topic == "roadmap" and not roadmap_allowed:
            return "roadmap_prerequisites_not_met"
        if _blank(raw.get("judgment")) or _blank(raw.get("question")):
            return "missing_or_empty_field:judgment_or_question"
        if _blank(raw.get("spoken_text")):
            return "missing_or_empty_field:spoken_text"
        if len(raw.get("spoken_text", "")) > _MAX_SPOKEN_TEXT_CHARS:
            return "spoken_text_too_long"
        if require_combine_structure:
            if _blank(raw.get("user_selection_summary")):
                return "missing_or_empty_field:user_selection_summary"
            if _blank(raw.get("proposal")):
                return "missing_or_empty_field:proposal"
        return None

    return _validate


def validate_spoken_text_speaker_reference(
    current_speaker_id: str,
    responding_to_speaker_id: str | None,
    spoken_text: str,
) -> str | None:
    """화자가 자기 역할을 상대방처럼 부르는 명백한 오류를 결정적으로 거부한다."""
    pattern = _SELF_REFERENCE_PATTERNS.get(current_speaker_id)
    if pattern and pattern.search(spoken_text or ""):
        trace_event(
            "IDEATION_SPEAKER_REFERENCE_WARNING",
            level=logging.WARNING,
            speaker=current_speaker_id,
            target=responding_to_speaker_id,
            reason="self_role_reference",
            text=sanitize_preview(spoken_text, limit=200),
        )
        return "spoken_text_self_role_reference"
    for mentioned_speaker_id, mentioned_pattern in _SELF_REFERENCE_PATTERNS.items():
        if mentioned_speaker_id != responding_to_speaker_id and mentioned_pattern.search(spoken_text or ""):
            trace_event(
                "IDEATION_SPEAKER_REFERENCE_WARNING",
                level=logging.WARNING,
                speaker=current_speaker_id,
                target=responding_to_speaker_id,
                mentioned=mentioned_speaker_id,
                reason="role_reference_target_mismatch",
                text=sanitize_preview(spoken_text, limit=200),
            )
            return "spoken_text_role_reference_target_mismatch"
    if any(phrase in (spoken_text or "") for phrase in _EMPTY_MEETING_PHRASES):
        return "spoken_text_report_like_or_empty_phrase"
    return None


def _looks_like_restatement(spoken_text: str, responding_to_content: str | None) -> bool:
    """거의 같은 어휘만 되풀이한 발언을 보수적으로 감지한다."""
    if not responding_to_content:
        return False
    tokenize = lambda text: {t for t in re.findall(r"[가-힣A-Za-z0-9]+", text.lower()) if len(t) >= 2}
    current = tokenize(spoken_text)
    previous = tokenize(responding_to_content)
    if len(current) < 5 or len(previous) < 5:
        return False
    return len(current & previous) / len(current | previous) >= 0.82


def _validate_discussion_response(
    raw: dict,
    discussion_stage: str = "initial_position",
    current_speaker_id: str | None = None,
    responding_to_speaker_id: str | None = None,
    responding_to_content: str | None = None,
) -> str | None:
    """용준/Claude(2026-07-21, 요청: 위원 간 실제 회의로 개편): discussion_stage가
    "review"(상대 의견 검토) 또는 "revision"(검토 반영 수정)이면 responding_to가 비어
    있으면 재시도를 유발한다 — "좋은 의견입니다" 류의 빈 상호참조를 막기 위한 최종
    방어선이다(1차 방어선은 프롬프트의 [상호참조 규칙]). agreement/concern은 최소 하나는
    실제 내용이 있어야 한다(둘 다 비어 있으면 상대 의견에 실질적으로 반응하지 않은 것)."""
    if _blank(raw.get("judgment")) or _blank(raw.get("reason")):
        return "missing_or_empty_field:judgment_or_reason"
    if len(raw.get("judgment", "")) > _MAX_JUDGMENT_CHARS:
        return "judgment_too_long"
    if len(raw.get("reason", "")) > _MAX_REASON_CHARS:
        return "reason_too_long"
    if len(raw.get("suggestion") or "") > _MAX_SUGGESTION_CHARS:
        return "suggestion_too_long"
    if _blank(raw.get("spoken_text")):
        return "missing_or_empty_field:spoken_text"
    if len(raw.get("spoken_text", "")) > _MAX_SPOKEN_TEXT_CHARS:
        return "spoken_text_too_long"
    if current_speaker_id:
        speaker_problem = validate_spoken_text_speaker_reference(
            current_speaker_id, responding_to_speaker_id, raw.get("spoken_text", "")
        )
        if speaker_problem:
            return speaker_problem
    if discussion_stage == "response" and _looks_like_restatement(
        raw.get("spoken_text", ""), responding_to_content
    ):
        return "spoken_text_restates_responding_message"
    # 용준/Claude(2026-07-21, 요청: 전문가 라운드테이블 전환) — 매 발언은 "현재 임시 결론"을
    # 반드시 담아야 한다(요청 4번). discussion_stage와 무관하게 항상 검증한다.
    if _blank(raw.get("interim_conclusion")):
        return "missing_or_empty_field:interim_conclusion"
    if len(raw.get("interim_conclusion", "")) > _MAX_INTERIM_CONCLUSION_CHARS:
        return "interim_conclusion_too_long"
    confirmed = raw.get("confirmed")
    if isinstance(confirmed, list) and len(confirmed) > _MAX_CONFIRMED_ITEMS:
        return "confirmed_too_many_items"
    unconfirmed = raw.get("unconfirmed")
    if isinstance(unconfirmed, list) and len(unconfirmed) > _MAX_UNCONFIRMED_ITEMS:
        return "unconfirmed_too_many_items"
    if discussion_stage == "response":
        if _blank(raw.get("responding_to")):
            return "missing_or_empty_field:responding_to"
        agreement = (raw.get("agreement") or "").strip()
        concern = (raw.get("concern") or "").strip()
        if not agreement and not concern:
            return "missing_or_empty_field:agreement_or_concern"
    # 용준/Claude(2026-07-22, 요청: 동적 전문가 회의로 개편) — 반복 발언 방지의 코드 강제
    # 지점(요청 17번): new_information이 비어 있으면 재시도를 유발한다.
    if _blank(raw.get("active_issue_id")):
        return "missing_or_empty_field:active_issue_id"
    new_information = raw.get("new_information")
    if not isinstance(new_information, list) or not any(
        isinstance(v, str) and v.strip() for v in new_information
    ):
        return "missing_or_empty_field:new_information"
    if responding_to_content and all(
        isinstance(value, str) and value.strip() and value.strip() in responding_to_content
        for value in new_information
        if isinstance(value, str) and value.strip()
    ):
        return "new_information_only_repeats_responding_message"
    if raw.get("needs_user_input") and _blank(raw.get("user_question")):
        return "missing_or_empty_field:user_question"
    return None


def _validate_facilitator_response(raw: dict) -> str | None:
    if _blank(raw.get("facilitator_summary")):
        return "missing_or_empty_field:facilitator_summary"
    if bool(raw.get("needs_user_decision")) and _blank(raw.get("user_question")):
        return "missing_or_empty_field:user_question"
    if _blank(raw.get("spoken_text")):
        return "missing_or_empty_field:spoken_text"
    if len(raw.get("spoken_text", "")) > _MAX_FACILITATOR_SPOKEN_TEXT_CHARS:
        return "spoken_text_too_long"
    return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_message_id() -> str:
    return f"MSG-{uuid.uuid4().hex[:10]}"


def _speaker_fields(persona_id: str) -> tuple[str, str]:
    """speaker_name/role은 LLM 출력을 신뢰하지 않고 persona_cards.json에서 가져온다 —
    배치형 _normalize_turn()이 speaker_id를 항상 호출부 값으로 덮어쓰는 것과 같은 이유
    (LLM이 이름/역할을 지어내 화면 표시가 흔들리는 것을 막기 위함)."""
    card = get_persona_card(persona_id)
    return card.get("display_name", persona_id), card.get("role", "")


def _referenced_ids(raw_ids: Any, known_message_ids: set[str]) -> list[str]:
    """LLM이 반환한 referenced_message_ids 중 실제로 존재하는 message_id만 남긴다 —
    존재하지 않는 id를 그대로 프론트에 흘려보내면(오인용 또는 프롬프트 인젝션 시도) 프론트가
    참조 링크를 못 찾아 깨진다."""
    if not isinstance(raw_ids, list):
        return []
    return [mid for mid in raw_ids if isinstance(mid, str) and mid in known_message_ids]


def _build_message(
    *,
    persona_id: str,
    round_number: int,
    message_type: str,
    content: str,
    referenced_message_ids: list[str],
    evidence: Any,
    structured: dict | None = None,
    message_id: str | None = None,
    grounding: dict | None = None,
) -> ConvMessage:
    """structured는 선택 필드다(요청 9번 — 프런트 "상세 보기" 토글용, 기존 content 문자열은
    그대로 유지한 채 순수 추가). opinion/agreement/disagreement 메시지만 값을 채우고
    (make_conv_discussion_node 참고), 질문/답변/설명/요약 메시지는 None으로 둔다 — 기존
    content 렌더링만으로도 완전한 정보이기 때문이다.

    grounding은 ground_claims()의 결과다(요청: RAG 근거 실제 활용 강화) — evidence(위)는
    "이번 턴에 주입된 검색 결과 전체"라는 기존 의미를 그대로 유지하고, grounding이 주어지면
    그중 실제로 주장과 연결·검증된 부분만 별도 필드로 추가한다. grounding이 없는 메시지
    타입(진행자 정리 등 claims 개념이 없는 메시지)은 빈 값으로 채운다."""
    speaker_name, role = _speaker_fields(persona_id)
    return ConvMessage(
        message_id=message_id or _new_message_id(),
        speaker_id=persona_id,
        speaker_name=speaker_name,
        role=role,
        round=round_number,
        message_type=message_type,  # type: ignore[typeddict-item]
        content=content,
        referenced_message_ids=referenced_message_ids,
        evidence=evidence or [],
        created_at=_now_iso(),
        structured=structured,
        claims=list(grounding["claims"]) if grounding else [],
        linked_evidence_refs=list(grounding["linked_evidence_refs"]) if grounding else [],
        supported_claim_count=grounding["supported_claim_count"] if grounding else 0,
        unsupported_claim_count=grounding["unsupported_claim_count"] if grounding else 0,
        # 용준/Claude(2026-07-22, 요청: claim 통계 의미 분리) — 순수 추가 필드. 구버전
        # 클라이언트는 무시하면 그대로 동작한다.
        accepted_claim_count=grounding["accepted_claim_count"] if grounding else 0,
        grounded_claim_count=grounding["grounded_claim_count"] if grounding else 0,
        expert_judgment_count=grounding["expert_judgment_count"] if grounding else 0,
        missing_information=list(grounding["missing_information"]) if grounding else [],
        evidence_status=grounding["evidence_status"] if grounding else None,
        sufficiency=(
            "sufficient"
            if grounding and grounding["evidence_status"] == "grounded"
            else "partial"
            if grounding and grounding["evidence_status"] in ("partially_grounded", "expert_judgment_only")
            else "insufficient"
            if grounding
            else None
        ),
    )


def _as_string_list(items: Any) -> list[str]:
    """LLM이 배열 대신 문자열·null·객체 등 다른 타입을 반환해도(구조화 출력이 100% 강제되지
    않는 JSON 모드의 한계) 안전하게 문자열 리스트로 정규화한다. 리스트가 아니면 통째로
    버린다 — 예를 들어 confirmed가 문자열 하나로 오면 그 문자열의 각 글자를 항목으로 쪼개는
    사고(예: "for item in raw_string")를 방지한다."""
    if not isinstance(items, list):
        return []
    return [str(v) for v in items if v is not None]


def _bullets(items: Any) -> str:
    values = _as_string_list(items)
    if not values:
        return "- (없음)"
    return "\n".join(f"- {v}" for v in values)


def _compose_question_content(spoken_text: str) -> str:
    """용준/Claude(2026-07-22, 요청: 보고서형 메시지 → 자연스러운 회의 발화 전환):
    화면에 실제로 보이는 content는 LLM이 만든 spoken_text 그대로다 — 예전에는 이 함수가
    judgment/question(및 후보 결합 시 user_selection_summary/proposal)을 [현재 판단]/
    [핵심 질문] 같은 보고서 헤더로 이어붙였지만, 그 구조는 채팅에서 보고서처럼 보인다는
    문제가 있었다. judgment/question/user_selection_summary/proposal은 여전히
    make_conv_question_node()가 message["structured"]에 그대로 저장한다 — 내부 상태와
    프롬프트 컨텍스트용으로는 계속 쓰이고, 화면에만 노출되지 않을 뿐이다."""
    return spoken_text.strip()


def _compose_discussion_content(spoken_text: str) -> str:
    """용준/Claude(2026-07-22, 요청: 보고서형 메시지 → 자연스러운 회의 발화 전환): 화면에
    실제로 보이는 content는 LLM이 만든 spoken_text 그대로다 — 예전에는 이 함수가
    judgment/reason/suggestion/responding_to/agreement/concern/revision/interim_conclusion/
    confirmed/unconfirmed를 역할별 헤더([기획 관점]/[기술 검토]/... discussion_headers_for가
    정하던 라벨)로 이어붙였지만, 그 구조는 채팅에서 보고서처럼 보인다는 문제가 있었다. 이
    필드들은 여전히 message["structured"]에 그대로 저장된다(make_conv_discussion_node 참고)
    — 내부 상태·다음 판단 근거로는 계속 쓰이고 화면에만 노출되지 않을 뿐이다."""
    return spoken_text.strip()


def _discussion_round_snapshot_text(
    persona_id: str,
    judgment: str,
    reason: str,
    suggestion: str,
    confirmed: Any,
    unconfirmed: Any,
    interim_conclusion: str = "",
    responding_to: str | None = None,
    agreement: str | None = None,
    concern: str | None = None,
    revision: str | None = None,
) -> str:
    """discussion_rounds(라운드별 발언 스냅샷, API에는 노출되지만 현재 프런트 채팅 UI는 쓰지
    않는 내부 회의록 아카이브)에 저장할 상세 텍스트를 조립한다. 채팅 말풍선(content/
    spoken_text)과는 별개 관심사라 역할별 헤더 라벨(discussion_headers_for, 요청: 보고서형
    메시지 개편으로 제거됨) 없이 고정된 일반 라벨을 쓴다 — 이 텍스트는 라이브 스트리밍 대상이
    아니므로 DISCUSSION_STREAM_FIELDS와 일치할 필요가 없다."""
    parts = [f"[판단]\n{judgment}", f"[근거]\n{reason}", f"[제안]\n{suggestion}"]
    if responding_to:
        parts.append(f"[상대 의견 검토]\n{responding_to}")
    if agreement:
        parts.append(f"[동의]\n{agreement}")
    if concern:
        parts.append(f"[우려/제약]\n{concern}")
    if revision:
        parts.append(f"[수정 내용]\n{revision}")
    parts.append(f"[임시 결론]\n{interim_conclusion}")
    parts.append(f"[확정 사항]\n{_bullets(confirmed)}")
    parts.append(f"[미확정 사항]\n{_bullets(unconfirmed)}")
    return "\n\n".join(parts)


# 용준/Claude(2026-07-22, 요청: 보고서형 메시지 → 자연스러운 회의 발화 전환) — 사용자에게
# 실제로 보여줄 텍스트는 이제 각 스키마의 spoken_text 필드 하나뿐이다(예전에는 judgment/
# question/reason/suggestion 등 여러 필드를 순서대로 헤더와 함께 이어붙였지만, 그 결과가
# 채팅에서 보고서처럼 보인다는 문제가 있었다). backend/app/api/routes/
# ideation_conversation_streaming.py의 스트리밍 llm_call이 이 목록을 그대로 써서 OpenAI
# 델타 안에서 spoken_text 값만 실시간으로 흘려보낸다 — 헤더가 없으므로 모든 목록의 두 번째
# 값은 항상 None이다.
QUESTION_STREAM_FIELDS: tuple[tuple[str, str | None], ...] = (("spoken_text", None),)
DISCUSSION_STREAM_FIELDS: tuple[tuple[str, str | None], ...] = (("spoken_text", None),)
FACILITATOR_SUMMARY_STREAM_FIELDS: tuple[tuple[str, str | None], ...] = (("spoken_text", None),)
EXPERT_DELEGATION_STREAM_FIELDS: tuple[tuple[str, str | None], ...] = (("spoken_text", None),)
# make_expert_delegation_message가 spoken_text 뒤에 항상 고정으로 덧붙이는 문구 — 스트리밍
# 종료 직후 화면에도 동일하게 붙여야 canonical 메시지와 스트리밍 미리보기가 일치한다.
EXPERT_DELEGATION_TRAILER = "\n\n사용자가 나중에 다른 방향을 제시하면 이 가정은 언제든 수정할 수 있습니다."

# 용준/Claude(2026-07-21, 요청: expert_delegation도 위원 간 상호 검토로 확장) — 담당 전문가의
# 임시 제안을 반대 역할 전문가가 검토하는 턴의 스트리밍 필드.
DELEGATION_REVIEW_STREAM_FIELDS: tuple[tuple[str, str | None], ...] = (("spoken_text", None),)
# 위임 흐름 전용 진행자 최종 권고안 — 사용자에게 되물을 필드가 스키마에 아예 없으므로
# (요청: "다시 사용자에게 같은 질문을 넘기면 안 됩니다") facilitator_summary와 달리 두 번째
# 스트림 필드가 없다.
DELEGATION_FACILITATOR_STREAM_FIELDS: tuple[tuple[str, str | None], ...] = (("spoken_text", None),)


# 용준/Claude(2026-07-23, 요청: RAG 근거 실제 활용 강화 — query 품질 개선) — 이전에는
# user_idea dict의 모든 값(제목/문제/대상 사용자/해결 방식/주요 기능/기술 접근/MVP 등)을
# 그대로 이어붙여 검색어로 썼다. 후보 필드가 많을수록 검색어가 길고 광범위해져, 지금 실제로
# 논의 중인 쟁점(active_issue, 예: "차별성")과 무관한 청크까지 상위권에 섞여 들어왔다 —
# 그 결과 검색 자체(raw/scoped/final target_count>0, criteria 검색됨)는 "성공"으로 보여도,
# 검색된 근거가 이번 쟁점과 실제로 관련이 없어 claim_grounding의 관련성 검사(ai.rag.
# evidence_linking.relevance.is_relevant_candidate)를 통과하지 못하거나, LLM 스스로
# "이번 쟁점과 무관하면 document_fact claim을 만들지 않는다"는 프롬프트 규칙(ideation_conv_
# discussion.txt [근거 인용 규칙])을 지켜 아예 인용을 시도하지 않는 결과로 이어졌다
# (linked_evidence_count=0, evidence_status="expert_judgment_only"). 이제 검색어를 (1) 아이디어
# 핵심 요약(제목/문제/해결 방식만, 필드 전부가 아니라), (2) 지금 실제로 다루는 쟁점,
# (3) 역할별 검토 관점, 세 부분으로 명시적으로 구분해 조합한다 — 이는 이번 발언의 실제
# 관심사에 검색을 집중시키기 위함이지, 단순히 키워드를 더 많이 넣는 것이 아니다.
_ROLE_QUERY_FOCUS: dict[str, str] = {
    "planning_expert": "사용자 가치와 문제 적합성, 공모전 심사 기준(혁신성·확장성 등), 기존 서비스 대비 차별성, 사업성·운영 구조",
    "dev_expert": "기술 구조와 구현 가능성, 데이터 수집·품질, 외부 시스템/API/센서 연동, 보안·성능·운영 위험, MVP 기술 범위",
}

# 용준/Claude(2026-07-23, 요청: 역할별 target query 필드 개선) — planning은 사용자 가치/차별화
# 관점의 필드가, dev는 기술 구현 관점의 필드가 검색에 더 적합하다. 이전에는 두 역할이 항상
# 같은 3개 필드(title/problem/solution)만 봤다 — planning에는 충분했지만 dev 검색에는 기술
# 정보(요구 데이터·기술 접근·MVP 범위·리스크)가 빠져 있었다. idea dict에 없는 필드는 그냥
# 건너뛴다(모든 후보가 이 필드를 다 채우지는 않는다).
_PLANNING_SUMMARY_FIELDS = ("title", "problem", "target_user", "solution", "differentiation", "core_value")
_DEV_SUMMARY_FIELDS = ("title", "solution", "main_features", "required_data", "technical_approach", "mvp_scope", "risks")
_IDEA_SUMMARY_FIELDS_BY_ROLE: dict[str, tuple[str, ...]] = {
    "planning_expert": _PLANNING_SUMMARY_FIELDS,
    "dev_expert": _DEV_SUMMARY_FIELDS,
}
_DEFAULT_IDEA_SUMMARY_FIELDS = ("title", "problem", "solution")
# 리스트 필드(main_features, risks 등)는 핵심 항목만 반영한다 — 후보에 기능이 10개 있어도
# 전부 이어붙이면 검색어가 다시 광범위해진다.
_MAX_SUMMARY_LIST_ITEMS = 3
# 검색어 전체(아이디어 요약 부분)가 지나치게 길어지지 않도록 문자 수 상한을 둔다.
_MAX_IDEA_SUMMARY_CHARS = 300

_ROLE_DEFAULT_RETRIEVAL_TOPIC: dict[str, str] = {
    "planning_expert": "차별성과 고객 가치",
    "dev_expert": "기술 구현 가능성",
}
# TOPIC_PRIORITY(질문 주제 slug) -> 검색어에 쓸 사람이 읽는 제목. 질문 턴(make_conv_question_
# node)의 question_topic과 같은 값 집합을 그대로 재사용한다 — 새 분류 체계를 만들지 않는다.
_TOPIC_ID_TITLES: dict[str, str] = {
    "problem": "문제 정의",
    "target_user": "목표 사용자",
    "core_value": "핵심 가치",
    "contest_fit": "공모전 적합성",
    "differentiation": "차별성과 고객 가치",
    "mvp": "MVP 범위",
    "data": "데이터 확보 방안",
    "ai_role": "AI 활용 방식",
    "roadmap": "확장 로드맵",
}


def _stringify_idea_field(value: object) -> str:
    """idea dict 값 하나를 검색어에 쓸 짧은 문자열로 정규화한다. 리스트는 앞의 핵심 항목
    몇 개만(_MAX_SUMMARY_LIST_ITEMS), 그 외 타입은 str()로 변환한다."""
    if isinstance(value, list):
        items = [str(v).strip() for v in value if str(v).strip()]
        return ", ".join(items[:_MAX_SUMMARY_LIST_ITEMS])
    if value is None:
        return ""
    return str(value).strip()


def _idea_core_summary(idea: object, persona_id: str | None = None) -> str:
    """user_idea/selected_idea dict에서 역할별 핵심 필드만 뽑아 짧게 요약한다(요청: 역할별
    target query 필드 개선 — planning/dev가 서로 다른 필드 집합을 본다). persona_id가
    없거나 매핑에 없으면 title/problem/solution만 쓰는 기존 기본값을 그대로 따른다. 값이
    빈 필드는 건너뛰고, 같은 문자열이 이미 포함돼 있으면 중복으로 넣지 않는다. 이 필드들이
    하나도 없는 구버전 idea(예: {"description": ...}만 있는 refinement 세션)는 있는 값
    전체를 이어붙인다. 결과가 너무 길면(_MAX_IDEA_SUMMARY_CHARS) 잘라낸다 — 의미 손실보다
    검색어 희석을 막는 것이 우선이다."""
    if isinstance(idea, dict):
        fields = _IDEA_SUMMARY_FIELDS_BY_ROLE.get(persona_id or "", _DEFAULT_IDEA_SUMMARY_FIELDS)
        seen: set[str] = set()
        core: list[str] = []
        for field in fields:
            text = _stringify_idea_field(idea.get(field))
            if text and text not in seen:
                seen.add(text)
                core.append(text)
        if core:
            summary = " / ".join(core)
        else:
            fallback: list[str] = []
            fallback_seen: set[str] = set()
            for value in idea.values():
                text = _stringify_idea_field(value)
                if text and text not in fallback_seen:
                    fallback_seen.add(text)
                    fallback.append(text)
            summary = " ".join(fallback)
    else:
        summary = str(idea or "")
    if len(summary) > _MAX_IDEA_SUMMARY_CHARS:
        summary = summary[:_MAX_IDEA_SUMMARY_CHARS].rstrip()
    return summary


def _active_issue_title(state: IdeationConvState) -> str | None:
    """지금 활성 쟁점(active_issue_id)의 사람이 읽는 제목을 open_issues/resolved_issues에서
    찾는다. 아직 쟁점 레코드가 만들어지지 않은 순간(예: 이번 발언에서 새로 여는 중)에는
    active_issue_id 자체(slug)를 대신 쓴다 — 검색어가 비게 두지 않기 위함이다."""
    issue_id = state.get("active_issue_id")
    if not issue_id:
        return None
    for issue in list(state.get("open_issues") or []) + list(state.get("resolved_issues") or []):
        if issue.get("issue_id") == issue_id:
            return issue.get("title") or issue_id
    return issue_id


def _slugify_issue_title(title: str) -> str:
    """issue title을 결정적 slug로 정규화한다(요청: Phase 1 shadow planner의 issue_id는
    불안정한 Python hash()를 쓰지 않는다) — 텍스트 자체가 같으면 항상 같은 slug가 나온다."""
    normalized = re.sub(r"[^0-9A-Za-z가-힣]+", "_", (title or "").strip()).strip("_")
    return normalized.lower() or "unknown_issue"


def resolve_effective_issue(state: IdeationConvState, persona_id: str | None = None) -> dict[str, str]:
    """용준/Claude(2026-07-23, Phase 1 "Shadow Deterministic Evidence Planner"): 이번 턴
    retrieval이 실제로 초점을 맞추는 쟁점을 issue_id/title 구조로 반환한다.
    resolve_retrieval_issue()와 정확히 같은 우선순위를 따르며(아래에서 그 함수가 이 함수의
    title만 재사용하도록 리팩터링했다 — 요청: "_topic_query()가 사용한 issue title/query와
    Planner의 issue가 반드시 동일") 반환하는 title 문자열은 항상 같다."""
    issue_id = state.get("active_issue_id")
    if issue_id:
        title = _active_issue_title(state) or issue_id
        return {"issue_id": issue_id, "title": title, "source": "active_issue_id"}

    if state.get("unresolved_issues"):
        title = " ".join(state["unresolved_issues"])
        return {"issue_id": _slugify_issue_title(title), "title": title, "source": "unresolved_issues"}

    resolved_topic_ids = list(state.get("resolved_topics") or [])
    resolved_issue_titles = {
        issue.get("title") for issue in (state.get("resolved_issues") or []) if issue.get("title")
    }
    for topic_id in remaining_topics_for(resolved_topic_ids):
        title = _TOPIC_ID_TITLES.get(topic_id, topic_id)
        if title not in resolved_issue_titles:
            return {"issue_id": topic_id, "title": title, "source": "topic_priority"}

    title = _ROLE_DEFAULT_RETRIEVAL_TOPIC.get(persona_id or "", "핵심 검토 사항")
    return {"issue_id": _slugify_issue_title(title), "title": title, "source": "role_default"}


def resolve_retrieval_issue(state: IdeationConvState, persona_id: str | None = None) -> str:
    """이번 턴 검색이 초점을 맞출 "지금 검토 중인 쟁점"의 제목을 다음 우선순위로 정한다(요청:
    첫 전문가 턴에도 실제 검토 쟁점 반영 — active_issue_id는 discussion 노드가 첫 발언을 마친
    "뒤"에야 열리므로, planning의 첫 발언 시점에는 항상 None이다. 이전에는 그 경우 idea 요약과
    role focus만 남아 검색어가 여전히 광범위했다):
    1) active_issue_id가 있으면 그 제목(_active_issue_title).
    2) 없으면 진행자가 이미 남긴 미해결 쟁점(unresolved_issues, discussion_facilitator가
       "unconfirmed"에서 채운다 — 있으면 TOPIC_PRIORITY보다 더 구체적인 최신 신호다), 그것도
       없으면 아직 해결되지 않은 TOPIC_PRIORITY 주제 중 우선순위가 가장 높은 것(question_topic
       체계를 그대로 재사용 — 이미 resolved_topics/resolved_issues에 있는 주제·제목은
       건너뛴다).
    3) 그것도 없으면(모든 주제가 이미 해결됐거나 두 목록이 모두 비어 있으면) 역할별 기본
       검토 주제로 폴백한다 — 검색어가 아이디어 요약뿐인 채로 비어 있는 상태를 만들지
       않는다.

    실제 title 계산은 resolve_effective_issue()에 위임한다(요청: retrieval과 Phase 1 shadow
    planner가 반드시 같은 title/query를 봐야 한다)."""
    return resolve_effective_issue(state, persona_id)["title"]


def _topic_query(state: IdeationConvState, persona_id: str | None = None) -> str:
    """이번 턴의 근거 검색어를 조립한다. persona_id를 넘기면 역할별 아이디어 요약 필드와
    검토 관점이 함께 반영돼 planning_expert/dev_expert가 서로 다른 검색어를 받는다(요청:
    역할별 검색 결과 차별화) — persona_id가 없으면(진행자 등 role_id가 없는 호출자) 이전과
    동일하게 기본 필드 요약 + 이슈만 반환한다."""
    parts: list[str] = []
    idea_summary = _idea_core_summary(state["user_idea"], persona_id)
    if idea_summary:
        parts.append(idea_summary)

    issue_title = resolve_retrieval_issue(state, persona_id)
    if issue_title:
        parts.append(f"현재 쟁점: {issue_title}")

    role_focus = _ROLE_QUERY_FOCUS.get(persona_id or "")
    if role_focus:
        parts.append(f"검토 관점: {role_focus}")

    if not parts:
        return idea_summary
    return " | ".join(parts)


def _runtime_scope_for(state: IdeationConvState) -> dict[str, Any]:
    """용준/Claude(2026-07-23, 요청: stale closure 수정) — evidence_lookup을 실제로 호출하는
    이 순간의 최신 state에서 session_id/selected_idea_document_id를 다시 읽는다. backend가
    만드는 evidence_lookup closure(ideation_conversation_preview.py::_evidence_lookup_for)는
    /reply 요청이 시작될 때(previous_state, candidate_selection 실행 전)의 값을 캡처하므로,
    같은 요청 안에서 후보가 방금 선택/변경돼도 그 closure 값은 갱신되지 않는다 — 실측
    확인된 버그(target upsert는 성공하지만 같은 요청의 다음 검색이 여전히
    selected_candidate_document_id=None으로 진행됨)의 원인이다. 노드가 검색을 호출하는
    이 지점에서는 candidate_selection 노드가 이미 state["selected_idea_document_id"]를
    갱신한 뒤이므로(그래프는 노드를 순차 실행한다), 여기서 다시 읽으면 항상 최신 값이다."""
    return {
        "session_id": state.get("session_id"),
        "selected_candidate_document_id": state.get("selected_idea_document_id"),
    }


def _last_user_answer(messages: list[ConvMessage]) -> dict | None:
    for msg in reversed(messages):
        if msg.get("message_type") == "answer":
            return msg
    return None


def conversation_context_for(state: IdeationConvState) -> dict[str, Any]:
    """질문/의견/재질문 판정 프롬프트가 공통으로 쓰는 대화 맥락 요약. ideation_conv_run.py의
    answer_sufficiency 게이트도 이 함수를 그대로 재사용한다(맥락 조립 로직 중복 방지)."""
    messages = state["messages"]
    return {
        "round": state["round"],
        "recent_messages": messages[-_RECENT_MESSAGES_LIMIT:],
        "last_user_answer": _last_user_answer(messages),
        "consensus_so_far": state["consensus"],
        "unresolved_issues": state["unresolved_issues"],
    }


_DISCUSSION_CONTEXT_MESSAGE_KEYS = (
    "message_id",
    "speaker_id",
    "speaker_name",
    "role",
    "message_type",
    "content",
    "responding_to",
    "referenced_message_ids",
    "created_at",
)


def _isolate_discussion_evidence_context(context: dict[str, Any]) -> dict[str, Any]:
    """Active evidence 턴의 현재 ref와 과거 메시지의 ref/chunk namespace를 격리한다.

    ConvMessage 전체에는 UI/세션 복원을 위한 evidence, claims, linked_evidence_refs와
    structured grounding 필드가 들어 있다. 이를 다음 discussion prompt에 그대로 직렬화하면
    LLM이 현재 턴 근거 대신 과거 턴의 E번호를 재사용할 수 있다. 대화 의미를 유지하는 필드만
    allow-list로 복사하며 원본 state/message는 수정하지 않는다.
    """

    def public_message(message: Any) -> Any:
        if not isinstance(message, dict):
            return message
        return {
            key: message[key]
            for key in _DISCUSSION_CONTEXT_MESSAGE_KEYS
            if key in message and message[key] is not None
        }

    isolated = dict(context)
    isolated["recent_messages"] = [public_message(item) for item in context.get("recent_messages") or []]
    last_user_answer = context.get("last_user_answer")
    isolated["last_user_answer"] = public_message(last_user_answer) if last_user_answer is not None else None
    return isolated


def _selection_context_for(state: IdeationConvState) -> dict[str, Any]:
    """용준/Claude(2026-07-21, 후보 결합 컨텍스트 보존): discovery 모드에서 후보를 선택/
    결합/추천한 직후부터 refinement 질문 프롬프트가 참조할 구조화된 선택 컨텍스트를
    만든다(요청 9번 — conversation_context의 최근 메시지에 우연히 포함되기를 기대하지
    않고 별도로 명시 전달). refinement로 시작했거나 아직 후보를 선택하지 않은 세션은
    selection_intent가 None이므로 빈 dict를 반환한다 — 템플릿은 빈 dict를 "선택 컨텍스트
    없음"으로 처리한다."""
    selection_intent = state.get("selection_intent")
    if not selection_intent:
        return {}
    return {
        "selection_intent": selection_intent,
        "user_selection_message": state.get("user_selection_message"),
        "source_candidates": state.get("source_candidates") or [],
        "merge_analysis": state.get("merge_analysis"),
        "selected_idea": state.get("selected_idea"),
    }


def _is_first_question_after_combine(state: IdeationConvState) -> bool:
    """이번 질문 노드 호출이 "후보 결합 직후 첫 전문가 메시지"인지 판별한다(요청 6번).
    candidate_selection 노드가 결합을 확정하면 항상 speaker_id="ideation_facilitator",
    message_type="summary"인 요약 메시지를 마지막에 추가한 뒤(ideation_conv_discovery.py::
    _resolve_selection) 같은 그래프 호출 안에서 곧바로 planning_question 노드로 이어지므로
    (ideation_conv_build.py::_route_after_candidate_selection), 이 시점의 "마지막 메시지"가
    그 요약 메시지인지만 보면 정확히 이 순간만 골라낼 수 있다 — 이후 질문(2번째 라운드 등)은
    마지막 메시지가 다른 종류이므로 False가 된다."""
    if state.get("selection_intent") != "combine":
        return False
    messages = state["messages"]
    if not messages:
        return False
    last = messages[-1]
    return last.get("speaker_id") == "ideation_facilitator" and last.get("message_type") == "summary"


def judge_answer_sufficiency(
    llm_call: LLMCall,
    persona_id: str,
    pending_question: str,
    user_answer: str,
    retry_count: int,
    conversation_context: dict[str, Any],
    expected_answer_type: str | None = None,
    user_idea: Any = None,
    idea_candidates: Any = None,
) -> dict[str, Any]:
    """사용자가 pending_question에 답한 직후, 이 메시지가 답변인지/설명 요청인지/불충분한
    답변인지 3분류로 판정한다(요청 3번 + 용어 설명 요청 오판 방지). ideation_conv_run.py::
    reply_ideation_conversation가 apply_user_answer로 phase를 넘기기 전에 호출한다 —
    그래프/노드 구조(질문·의견 노드, 엣지)는 건드리지 않고 별도의 짧은 판정 호출 하나만
    앞에 끼워 넣는 방식이라, 기존 라운드 진행 로직과 완전히 분리돼 있다.

    expected_answer_type(질문 노드가 만든 이번 질문의 기대 답변 유형 — 예: "preference",
    "selection")을 함께 넘긴다. 이 판정은 "방금 pending_question이 요구한 것에 답했는가"만
    보는 것이지 "아이디어 전체가 충분히 구체적인가"를 보는 게 아니다(요청: 답변 충분성과
    아이디어 완성도 분리) — expected_answer_type이 preference/selection이면 하나를 명확히
    선택한 것만으로 충분하다고 판정하도록 프롬프트가 요구 수준을 낮춘다. None이면(질문
    노드가 값을 만들지 못했거나 구버전 응답) 기존의 일반 기준으로만 판정한다.

    user_idea/idea_candidates는 clarification_request일 때 "현재 후보와 대화 맥락에 맞는"
    선택지를 만들기 위한 근거 자료다(요청 사항 예시처럼 "두 후보를 고려하면 생활비 절감과
    안전 향상이 주요 선택지입니다"처럼 실제 아이디어에 근거한 예시를 만들려면 필요하다).

    반환값의 answer_type이 세 값 중 하나다("answer"/"clarification_request"/
    "insufficient_answer"). 하위 호환을 위해 is_sufficient(answer_type=="answer")도 함께
    돌려준다 — LLM이 구버전 스키마(is_sufficient 불리언만)를 반환해도 answer_type이 없으면
    그 값으로 answer/insufficient_answer를 유추한다(clarification_request는 유추할 수 없으므로
    이 경우 절대 선택되지 않는다 — 구버전 스키마는 애초에 그 개념을 모른다).

    판정 호출이 실패(파싱 실패 등)하면 안전하게 "충분함"으로 fail-open한다 — 이 판정은
    부가적인 품질 게이트일 뿐 회의의 핵심 콘텐츠 생성이 아니므로, 판정 자체의 인프라
    오류로 사용자가 답변을 진행하지 못하게 막는 것은 과도하다(질문/의견/종합 노드처럼
    phase="failed"로 보내지 않는다)."""
    prompt = build_ideation_conv_sufficiency_prompt(
        persona_id,
        pending_question,
        user_answer,
        retry_count,
        conversation_context,
        expected_answer_type,
        user_idea,
        idea_candidates,
    )
    raw, ok = _safe_call_json(llm_call, prompt)
    if not ok or raw is None:
        return {
            "answer_type": "answer",
            "is_sufficient": True,
            "reason": "판정 응답 파싱 실패로 자동 통과",
            "follow_up_question": None,
            "clarification_response": None,
        }

    answer_type = raw.get("answer_type")
    if answer_type not in _VALID_ANSWER_TYPES:
        # 하위 호환 — 구버전 스키마(is_sufficient 불리언만)로 응답한 경우 유추한다.
        answer_type = "answer" if bool(raw.get("is_sufficient", True)) else "insufficient_answer"

    return {
        "answer_type": answer_type,
        "is_sufficient": answer_type == "answer",
        "reason": raw.get("reason", ""),
        "follow_up_question": raw.get("follow_up_question") or None,
        "clarification_response": raw.get("clarification_response") or None,
    }


def make_follow_up_message(*, persona_id: str, round_number: int, reason: str, follow_up_question: str) -> ConvMessage:
    """answer_sufficiency 판정이 불충분으로 나왔을 때 사용자에게 다시 보여줄 재질문 메시지를
    만든다. _build_message를 그대로 재사용해 message_id/speaker_name/role 등 필드 규칙을
    질문/의견 메시지와 통일한다.

    용준/Claude(2026-07-22, 요청: 보고서형 메시지 → 자연스러운 회의 발화 전환): 예전에는
    reason/follow_up_question을 [재질문]/[핵심 질문] 헤더로 나눠 보여줬지만, 이 두 문장은
    이미 자연스럽게 이어지는 문장이라(judge_answer_sufficiency의 reason은 "왜 다시 묻는지",
    follow_up_question은 "무엇을 묻는지") 헤더 없이 한 문단으로 이어붙인다."""
    content = f"{reason}\n\n{follow_up_question}".strip()
    return _build_message(
        persona_id=persona_id,
        round_number=round_number,
        message_type="question",
        content=content,
        referenced_message_ids=[],
        evidence=[],
    )


def make_clarification_message(*, persona_id: str, round_number: int, clarification_response: str) -> ConvMessage:
    """사용자가 용어 설명/예시/선택지를 요청했을 때(answer_type="clarification_request")
    보여줄 메시지를 만든다. clarification_response는 이미 "설명 + 3~5개 선택지 + 다시 던지는
    핵심 질문"을 한 덩어리로 담고 있다(ideation_conv_sufficiency.txt::[명확화 응답 작성
    규칙] 참고) — 이 함수는 그 값을 메시지 스키마로 감싸기만 한다.

    용준/Claude(2026-07-22, 요청: 보고서형 메시지 → 자연스러운 회의 발화 전환): [설명] 라벨을
    더 이상 붙이지 않는다 — clarification_response 자체가 이미 완결된 자연스러운 응답이다."""
    content = clarification_response.strip()
    return _build_message(
        persona_id=persona_id,
        round_number=round_number,
        message_type="question",
        content=content,
        referenced_message_ids=[],
        evidence=[],
    )


def _validate_expert_delegation_response(raw: dict, stage: str = "initial") -> str | None:
    if _blank(raw.get("proposal")) or _blank(raw.get("reason")) or _blank(raw.get("assumption")):
        return "missing_or_empty_field:proposal_or_reason_or_assumption"
    if _blank(raw.get("spoken_text")):
        return "missing_or_empty_field:spoken_text"
    if len(raw.get("spoken_text", "")) > _MAX_SPOKEN_TEXT_CHARS:
        return "spoken_text_too_long"
    if stage == "revision":
        if _blank(raw.get("responding_to")) or _blank(raw.get("revision")):
            return "missing_or_empty_field:responding_to_or_revision"
    return None


def generate_expert_delegation_proposal(
    llm_call: LLMCall,
    persona_id: str,
    pending_question: str,
    notice_and_criteria: Any,
    user_idea: Any,
    retrieved_evidence: Any,
    conversation_context: dict[str, Any],
    stage: str = "initial",
    counterpart_review: Any = None,
) -> tuple[dict | None, bool, int]:
    """용준/Claude(2026-07-21, 요청: "모르겠다" UX 개선): answer_type="expert_delegation"일
    때(사용자가 pending_question에 답하는 대신 전문가 판단에 맡겼을 때) 담당 페르소나가
    자신의 평가 범위 안에서 합리적인 방향을 "임시 가정"으로 제안하게 만든다. 질문/의견
    노드와 같은 구조화 검증·재시도 정책(_safe_call_structured_json, 최대 1회 재시도)을
    그대로 재사용한다 — 실패 시(재시도 후에도 무효) 호출부가 다른 콘텐츠 생성 노드와
    동일하게 phase="failed"로 처리한다.

    stage/counterpart_review(용준/Claude(2026-07-21, 요청: expert_delegation도 위원 간
    상호 검토로 확장): stage="revision"이면 상대 전문가의 검토(counterpart_review)를
    반영해 원래 제안을 수정하거나 유지한다 — responding_to/revision이 비어 있으면 재시도를
    유발한다(빈 상호참조 방지, discussion 노드와 동일한 정책)."""
    prompt = build_ideation_conv_expert_delegation_prompt(
        persona_id,
        notice_and_criteria,
        user_idea,
        retrieved_evidence,
        conversation_context,
        pending_question,
        stage=stage,
        counterpart_review=counterpart_review,
    )
    validate = lambda raw, _stage=stage: _validate_expert_delegation_response(raw, _stage)  # noqa: E731
    return _safe_call_structured_json(llm_call, prompt, validate, f"expert_delegation__{persona_id}")


def _validate_expert_delegation_review_response(raw: dict) -> str | None:
    if _blank(raw.get("judgment")) or _blank(raw.get("reason")) or _blank(raw.get("responding_to")):
        return "missing_or_empty_field:judgment_or_reason_or_responding_to"
    if _blank(raw.get("recommendation")):
        return "missing_or_empty_field:recommendation"
    if _blank(raw.get("spoken_text")):
        return "missing_or_empty_field:spoken_text"
    if len(raw.get("spoken_text", "")) > _MAX_SPOKEN_TEXT_CHARS:
        return "spoken_text_too_long"
    agreement = (raw.get("agreement") or "").strip()
    concern = (raw.get("concern") or "").strip()
    if not agreement and not concern:
        return "missing_or_empty_field:agreement_or_concern"
    return None


def generate_expert_delegation_review(
    llm_call: LLMCall,
    counterpart_persona_id: str,
    pending_question: str,
    notice_and_criteria: Any,
    user_idea: Any,
    retrieved_evidence: Any,
    conversation_context: dict[str, Any],
    proposal_under_review: Any,
) -> tuple[dict | None, bool, int]:
    """용준/Claude(2026-07-21, 요청: expert_delegation도 위원 간 상호 검토로 확장): 담당
    전문가의 임시 제안을 반대 역할 전문가(counterpart_persona_id)가 자신의 평가 범위에서
    검토하게 만든다. proposal_under_review는 generate_expert_delegation_proposal()의 raw
    반환값(dict)을 그대로 넘긴다."""
    prompt = build_ideation_conv_expert_delegation_review_prompt(
        counterpart_persona_id,
        notice_and_criteria,
        user_idea,
        retrieved_evidence,
        conversation_context,
        pending_question,
        proposal_under_review,
    )
    return _safe_call_structured_json(
        llm_call, prompt, _validate_expert_delegation_review_response, f"expert_delegation_review__{counterpart_persona_id}"
    )


def _validate_expert_delegation_facilitator_response(raw: dict) -> str | None:
    if _blank(raw.get("final_recommendation")):
        return "missing_or_empty_field:final_recommendation"
    if _blank(raw.get("spoken_text")):
        return "missing_or_empty_field:spoken_text"
    if len(raw.get("spoken_text", "")) > _MAX_FACILITATOR_SPOKEN_TEXT_CHARS:
        return "spoken_text_too_long"
    return None


def generate_expert_delegation_facilitator_recommendation(
    llm_call: LLMCall,
    notice_and_criteria: Any,
    pending_question: str,
    proposal: Any,
    review: Any,
    revision: Any,
) -> tuple[dict | None, bool, int]:
    """용준/Claude(2026-07-21, 요청: expert_delegation도 위원 간 상호 검토로 확장): 제안 ->
    검토 -> (있다면) 수정까지 끝난 뒤 진행자가 최종 권고안 하나로 정리하게 만든다. 출력
    스키마에 사용자 재질문 필드가 없어 구조적으로 같은 질문을 반복할 수 없다."""
    prompt = build_ideation_conv_expert_delegation_facilitator_prompt(
        notice_and_criteria, pending_question, proposal, review, revision
    )
    return _safe_call_structured_json(
        llm_call, prompt, _validate_expert_delegation_facilitator_response, "expert_delegation_facilitator"
    )


def _compose_expert_delegation_content(spoken_text: str) -> str:
    """용준/Claude(2026-07-22, 요청: 보고서형 메시지 → 자연스러운 회의 발화 전환): 화면에
    실제로 보이는 content는 spoken_text에 고정 안내 문구(이 제안이 임시 가정이라는 사실,
    요청 10번)를 이어붙인 것이다 — 예전에는 proposal/reason/assumption을 [○○ 제안]/[제안
    이유]/[임시 가정] 헤더로 이어붙였지만, 그 구조는 채팅에서 보고서처럼 보인다는 문제가
    있었다. 안내 문구는 LLM이 빠뜨려도 항상 보장되도록 여기서 고정으로 덧붙인다(요청
    10번 그대로 유지) — 스트리밍 시 EXPERT_DELEGATION_TRAILER가 spoken_text 델타가 닫힌
    직후 같은 문구를 흘려보낸다."""
    return f"{spoken_text.strip()}\n\n사용자가 나중에 다른 방향을 제시하면 이 가정은 언제든 수정할 수 있습니다."


def make_expert_delegation_message(
    *,
    persona_id: str,
    round_number: int,
    spoken_text: str,
    proposal: str,
    reason: str,
    assumption: str,
    referenced_message_ids: Any,
    evidence: Any,
    known_message_ids: set[str],
    responding_to: str | None = None,
    revision: str | None = None,
) -> ConvMessage:
    content = _compose_expert_delegation_content(spoken_text)
    return _build_message(
        persona_id=persona_id,
        round_number=round_number,
        message_type="opinion",
        content=content,
        referenced_message_ids=_referenced_ids(referenced_message_ids, known_message_ids),
        evidence=evidence,
        structured={
            "proposal": proposal,
            "reason": reason,
            "assumption": assumption,
            "responding_to": responding_to,
            "revision": revision,
        },
    )


def _compose_expert_delegation_review_content(spoken_text: str) -> str:
    """용준/Claude(2026-07-22, 요청: 보고서형 메시지 → 자연스러운 회의 발화 전환): 화면에
    실제로 보이는 content는 spoken_text 그대로다 — 예전에는 judgment/reason/responding_to/
    agreement/concern/recommendation을 [검토]/[근거]/[제안 검토]/... 헤더로 이어붙였지만,
    그 필드들은 여전히 structured에 저장되어 내부 상태로 쓰인다."""
    return spoken_text.strip()


def make_expert_delegation_review_message(
    *,
    persona_id: str,
    round_number: int,
    raw: dict,
    known_message_ids: set[str],
    evidence: Any = None,
) -> ConvMessage:
    stance = raw.get("stance")
    if stance not in _VALID_DISCUSSION_STANCES:
        stance = "보완"
    message_type = _STANCE_TO_MESSAGE_TYPE.get(stance, "opinion")
    judgment = raw.get("judgment", "")
    reason = raw.get("reason", "")
    responding_to = raw.get("responding_to", "")
    agreement = raw.get("agreement") or ""
    concern = raw.get("concern") or ""
    recommendation = raw.get("recommendation", "")
    content = _compose_expert_delegation_review_content(raw.get("spoken_text", ""))
    return _build_message(
        persona_id=persona_id,
        round_number=round_number,
        message_type=message_type,
        content=content,
        referenced_message_ids=_referenced_ids(raw.get("referenced_message_ids"), known_message_ids),
        # 용준/Claude(2026-07-22, RAG 근거 유실 수정): raw.get("evidence") 대신 호출부가
        # 실제 RAG 검색으로 얻어 프롬프트에 주입한 근거(evidence 인자)를 저장한다.
        evidence=evidence,
        structured={
            "judgment": judgment,
            "reason": reason,
            "responding_to": responding_to,
            "agreement": agreement,
            "concern": concern,
            "recommendation": recommendation,
            "stance": stance,
        },
    )


def make_expert_delegation_facilitator_message(*, round_number: int, raw: dict) -> ConvMessage:
    """요청: "다시 사용자에게 같은 질문을 넘기면 안 됩니다" — 이 메시지는 질문 필드를 아예
    갖지 않는 스키마(generate_expert_delegation_facilitator_recommendation)의 결과만 담으므로
    구조적으로 재질문이 불가능하다.

    용준/Claude(2026-07-22, 요청: 보고서형 메시지 → 자연스러운 회의 발화 전환): 화면에 실제로
    보이는 content는 spoken_text(1~2문장) 그대로다 — final_recommendation(결정 어조의 상세
    권고)과 considerations([참고 사항] 목록)는 더 이상 content에 붙지 않고 structured에만
    남는다."""
    final_recommendation = raw.get("final_recommendation", "")
    considerations = _as_string_list(raw.get("considerations"))
    content = raw.get("spoken_text", "").strip()
    return _build_message(
        persona_id="ideation_facilitator",
        round_number=round_number,
        message_type="summary",
        content=content,
        referenced_message_ids=[],
        evidence=[],
        structured={
            "agreements": _as_string_list(raw.get("agreements")),
            "considerations": considerations,
            "final_recommendation": final_recommendation,
        },
    )


def make_conv_question_node(
    persona_id: str,
    awaiting_phase: str,
    llm_call: LLMCall,
    evidence_lookup: EvidenceLookup | None = None,
    ground_claims: ClaimGroundingFn | None = None,
) -> Callable[[IdeationConvState], dict]:
    """기획 전문가(planning_expert)/개발 전문가(dev_expert)의 "질문 턴" 노드를 만든다.
    질문 하나를 만들고 나면 반드시 awaiting_phase로 멈춘다 — 이 노드 자신은 절대
    다음 전문가로 이어가지 않는다(요청 4번: 기획 질문 직후, 개발 질문 직후 각각 정지)."""

    def node(state: IdeationConvState) -> dict:
        query = _topic_query(state, persona_id)
        runtime_scope = _runtime_scope_for(state)
        trace_event(
            "IDEATION_EVIDENCE_LOOKUP_SCOPE",
            session_id=runtime_scope["session_id"],
            speaker=persona_id,
            selected_candidate_document_id=runtime_scope["selected_candidate_document_id"],
            selected_candidate_document_id_source="runtime_graph_state",
        )
        retrieved = call_evidence_lookup(evidence_lookup, persona_id, query, runtime_scope=runtime_scope)
        context = conversation_context_for(state)
        # 용준/Claude(2026-07-21, 질문 주제 구조화): resolved_topics는 state["resolved_topics"]
        # 그대로 읽는다(요청: 답변이 "answer"로 판정되어 다음 단계로 넘어갈 때만 추가되므로,
        # 후보 데이터에 problem/target_user 등이 있어도 여기 없으면 아직 미확정이다 —
        # discovery 후보는 전문가 초안일 뿐 사용자 확정이 아니라는 요청 4번 원칙이 바로
        # 이 지점에서 지켜진다: 후보 내용은 프롬프트의 user_idea/idea_candidates 컨텍스트로만
        # 전달되고, resolved_topics 판단에는 전혀 영향을 주지 않는다).
        resolved_topics = list(state.get("resolved_topics") or [])
        remaining_topics = remaining_topics_for(resolved_topics)
        roadmap_allowed = "roadmap" in remaining_topics
        selection_context = _selection_context_for(state)
        require_combine_structure = _is_first_question_after_combine(state)
        prompt = build_ideation_conv_question_prompt(
            persona_id,
            state["notice_and_criteria"],
            state["user_idea"],
            retrieved,
            context,
            resolved_topics=resolved_topics,
            remaining_topics=remaining_topics,
            roadmap_allowed=roadmap_allowed,
            selection_context=selection_context,
            require_combine_structure=require_combine_structure,
        )
        validate = _make_validate_question_response(resolved_topics, roadmap_allowed, require_combine_structure)
        raw, ok, attempts = _safe_call_structured_json(llm_call, prompt, validate, f"question__{persona_id}")
        used = state.get("llm_calls_used", 0) + attempts
        if not ok:
            return {"phase": "failed", "failed_node": f"question__{persona_id}", "llm_calls_used": used}

        raw, grounding, used = _ground_and_finalize_claims(
            persona_id=persona_id,
            raw=raw,
            retrieved=retrieved,
            prompt=prompt,
            llm_call=llm_call,
            validate=validate,
            used=used,
            ground_claims_fn=ground_claims,
        )

        judgment = raw.get("judgment", "")
        question = raw.get("question", "")
        question_topic = raw.get("question_topic")  # validate()가 이미 TOPIC_PRIORITY 소속을 보장한다.
        known_ids = {m["message_id"] for m in state["messages"]}
        message = _build_message(
            persona_id=persona_id,
            round_number=state["round"],
            message_type="question",
            content=_compose_question_content(raw.get("spoken_text", "")),
            referenced_message_ids=_referenced_ids(raw.get("referenced_message_ids"), known_ids),
            # 용준/Claude(2026-07-22, RAG 근거 유실 수정): 예전에는 raw.get("evidence")로 LLM이
            # JSON 응답에 자발적으로 되돌려준 evidence만 저장했다 — 이 필드는 검증되지 않는
            # 선택 필드라 대부분의 응답이 비워 보냈고, 그 결과 retrieved(위에서 RAG 검색으로
            # 실제로 찾아 프롬프트에 주입한 근거)가 있어도 메시지·로그(IDEATION_TURN_END의
            # evidence_count)에는 항상 0으로 남았다. 프롬프트에 실제로 삽입한 근거(retrieved)를
            # 그대로 메시지 evidence로 저장해야 "삽입된 근거 수"가 사실과 일치한다.
            evidence=retrieved,
            grounding=grounding,
            # 용준/Claude(2026-07-22, 요청: 보고서형 메시지 → 자연스러운 회의 발화 전환) —
            # judgment/question/user_selection_summary/proposal은 더 이상 content에 헤더로
            # 노출되지 않으므로, 내부 상태·다음 턴 프롬프트 컨텍스트로 계속 쓸 수 있도록
            # structured에 옮겨 담는다(순수 추가 — content가 대체됐을 뿐 정보는 유지된다).
            structured={
                "judgment": judgment,
                "question": question,
                "question_topic": question_topic,
                "user_selection_summary": raw.get("user_selection_summary"),
                "proposal": raw.get("proposal"),
            },
        )
        # expected_answer_type은 선택 필드다 — LLM이 만들지 않거나(구버전 프롬프트 응답 등)
        # 허용값 밖의 값을 반환해도 질문 생성 자체를 실패시키지 않고 None으로 저장한다
        # (sufficiency 판정이 기존의 일반 기준으로 대체 판정한다).
        expected_answer_type = raw.get("expected_answer_type")
        if expected_answer_type not in _VALID_EXPECTED_ANSWER_TYPES:
            expected_answer_type = None
        return {
            "messages": [message],
            "phase": awaiting_phase,
            # 재질문 판정(judge_answer_sufficiency)이 참조할 "질문 그 자체"만 저장한다
            # (judgment 설명까지 합친 표시용 content 전체가 아니라).
            "pending_question": question or message["content"],
            "pending_expected_answer_type": expected_answer_type,
            "pending_question_topic": question_topic,
            "llm_calls_used": used,
        }

    return node


# 용준/Claude(2026-07-22, 요청: 동적 전문가 회의로 개편): 고정 그래프 시퀀스(기획 1회 → 개발
# 1회 → [조건부 수정] → 진행자 정리)를 쟁점 단위 동적 라우팅으로 교체하면서 REVISION_TRIGGER_
# STANCES(수정 턴 실행 여부를 stance로 게이팅하던 옛 메커니즘)는 더 이상 그래프 라우팅에
# 쓰이지 않는다 — 다음 발언자는 이제 항상 recommended_next_speaker(코드가 검증)로 정해진다.
# 이름은 하위 호환을 위해 유지한다(다른 모듈이 import할 수 있음 — grep으로 미사용 확인 필요).
REVISION_TRIGGER_STANCES = {"반박", "조건부_동의", "대안_제시"}

_DISCUSSION_COUNTERPART = {"planning_expert": "dev_expert", "dev_expert": "planning_expert"}
_VALID_NEXT_SPEAKERS = {"planning_expert", "dev_expert", "ideation_facilitator", "user"}

# 용준/Claude(2026-07-22, 요청: 동적 전문가 회의로 개편) — 발언 수/종료 조건 캡. 쟁점 하나당
# 최소/최대 발언 수와 라운드(=API 호출 1회 안에서 이어지는 전문가 발언 구간) 전체의 최소/최대
# 발언 수를 분리한다 — 라운드 캡은 "언제 진행자가 개입해도 되는가"(consensus_reached 판단에
# 최소한의 논의는 있었는지), 쟁점 캡은 "같은 쟁점에서 무한히 반론이 오가는 것"을 막는다.
MIN_EXPERT_TURNS_PER_ISSUE = 2
MAX_EXPERT_TURNS_PER_ISSUE = 6
MIN_EXPERT_TURNS_PER_ROUND = 4
MAX_EXPERT_TURNS_PER_ROUND = 8


def _most_recent_message_by(messages: list[ConvMessage], speaker_id: str) -> ConvMessage | None:
    for msg in reversed(messages):
        if msg.get("speaker_id") == speaker_id:
            return msg
    return None


def _discussion_stage_for(state: IdeationConvState, persona_id: str) -> str:
    """용준/Claude(2026-07-22, 요청: 동적 전문가 회의로 개편): 이번 발언이 "직전 발언에
    반응하는 것"인지를 결정한다. previous_speaker(라운드 내 마지막 "전문가" 발언자) 대신
    messages의 마지막 메시지가 실제로 상대 전문가인지를 직접 본다 — 그래야 사용자가
    "잠시만"으로 끼어들거나(interjection) 진행자가 방금 라운드를 열었을 때도, 다음 발언이
    "상대 전문가에게 반응"이 아니라 "방금 들어온 메시지(사용자/진행자)에 반응"으로 정확히
    분류된다(요청 6번 — 사용자 개입 메시지가 다음 전문가 발언의 responding_to로 잡혀야
    한다)."""
    messages = state["messages"]
    last = messages[-1] if messages else None
    counterpart = _DISCUSSION_COUNTERPART.get(persona_id)
    if last is not None and last.get("speaker_id") == counterpart:
        return "response"
    return "initial_position"


def _responding_to_for(state: IdeationConvState, persona_id: str, discussion_stage: str) -> ConvMessage | None:
    """이번 발언이 실제로 무엇에 반응하는지(responding_to_message_id/speaker_id)를 코드가
    결정적으로 찾는다 — LLM이 존재하지 않는 id를 지어낼 위험을 피하기 위해 절대 LLM에게
    맡기지 않는다.

    "response"면 상대 페르소나가 가장 최근에 남긴 메시지를 찾는다. "initial_position"이면
    직전 메시지가 사용자 개입일 때만 그 사용자 메시지를 대상으로 삼고, 진행자 안건/정리는
    대화 컨텍스트로만 참고한다."""
    messages = state["messages"]
    if discussion_stage == "response":
        counterpart = _DISCUSSION_COUNTERPART.get(persona_id)
        target = _most_recent_message_by(messages, counterpart) if counterpart else None
        if target is not None:
            return target
    # 최초 입장에서는 방금 들어온 사용자 개입에만 직접 응답한다. 진행자의 안건/정리는
    # 대화 컨텍스트로 참고할 뿐 전문가 상호검토의 responding_to 대상으로 저장하지 않는다.
    if messages:
        latest = messages[-1]
        if latest.get("speaker_id") == "user":
            return latest
    return None


_ISSUE_ID_SLUG_RE = re.compile(r"[^a-z0-9_]+")


def _fallback_issue_id(state: IdeationConvState) -> str:
    """LLM이 active_issue_id를 비워서 돌려주는 경우(구조화 검증이 이미 재시도를 유발하므로
    정상 흐름에서는 거의 도달하지 않는다)에 대비한 최후 방어값 — 이미 열린 쟁점이 있으면 그걸
    그대로 쓰고, 없으면 라운드 번호 기반 slug를 만든다."""
    open_issues = state.get("open_issues") or []
    if open_issues:
        return open_issues[-1]["issue_id"]
    return f"issue_r{state.get('round', 1)}"


def _update_issue_records(
    *,
    open_issues: list[dict],
    resolved_issues: list[dict],
    persona_id: str,
    issue_id: str,
    issue_title: str,
    position_text: str,
    resolved: bool,
    resolution_text: str,
) -> tuple[list[dict], list[dict]]:
    """용준/Claude(2026-07-22, 요청: 동적 전문가 회의로 개편): open_issues/resolved_issues를
    코드가 결정적으로 갱신한다 — LLM은 issue_resolved bool만 판단하고, 레코드 생성·이동은
    항상 여기서 수행한다(라우팅이 LLM 추천을 그대로 신뢰하지 않는 것과 같은 원칙)."""
    open_issues = list(open_issues)
    position_key = "planning_position" if persona_id == "planning_expert" else "development_position"

    idx = next((i for i, issue in enumerate(open_issues) if issue["issue_id"] == issue_id), None)
    if idx is None:
        record = {
            "issue_id": issue_id,
            "title": issue_title or issue_id,
            "status": "open",
            "planning_position": None,
            "development_position": None,
            "resolution": None,
            "turns": 0,
        }
        open_issues.append(record)
        idx = len(open_issues) - 1

    record = dict(open_issues[idx])
    record[position_key] = position_text
    record["turns"] = record.get("turns", 0) + 1
    if issue_title:
        record["title"] = issue_title

    if resolved:
        record["status"] = "resolved"
        record["resolution"] = resolution_text
        resolved_issues = list(resolved_issues) + [record]
        open_issues = [issue for i, issue in enumerate(open_issues) if i != idx]
    else:
        open_issues[idx] = record

    return open_issues, resolved_issues


def _route_next_expert_turn(state: IdeationConvState) -> str:
    """용준/Claude(2026-07-22, 요청: 동적 전문가 회의로 개편): "기획 1회 → 개발 1회 → 진행자
    정리"로 고정됐던 그래프 엣지를 대체하는 조건부 라우터. 쟁점·반론·발언 캡에 따라 다음에
    실행할 노드("planning_expert"/"dev_expert"/"facilitator"/"failed")를 계산한다.
    ideation_conv_build.py가 planning_expert_discussion/dev_expert_discussion 두 노드 모두에서
    이 함수로 조건부 엣지를 건다(양방향 — 기획이 개발을 부르고, 개발도 기획을 다시 부를 수
    있다). LLM이 추천한 recommended_next_speaker를 그대로 신뢰하지 않고, 캡·상태와 함께
    검증한 뒤에만 그 노드로 보낸다."""
    def routed(selected: str, reason: str, recommended: str | None = None) -> str:
        last_message = state["messages"][-1] if state.get("messages") else None
        last_structured = (last_message.get("structured") or {}) if last_message else {}
        active_issue_id = state.get("active_issue_id")
        issue_turn_count = next(
            (
                issue.get("turns", 0)
                for issue in (state.get("open_issues") or [])
                if issue.get("issue_id") == active_issue_id
            ),
            0,
        )
        trace_event(
            "IDEATION_ROUTE_DECISION",
            session_id=state.get("session_id"),
            current=last_message.get("speaker_id") if last_message else None,
            recommended=recommended or last_structured.get("recommended_next_speaker"),
            selected=selected,
            validated_next=selected,
            issue=active_issue_id,
            resolved=last_structured.get("issue_resolved"),
            needs_counterpart=last_structured.get("needs_counterpart_response"),
            required_counterpart=state.get("required_counterpart_speaker_id"),
            counterpart_review_completed=state.get("counterpart_review_completed"),
            turn_count=state.get("expert_turn_count", 0),
            issue_turn_count=issue_turn_count,
            stop_reason=reason if selected == "facilitator" else None,
            reason=reason,
            route_reason=reason,
        )
        return selected

    if state.get("phase") == "failed":
        return routed("failed", "phase_failed")

    messages = state["messages"]
    last = messages[-1] if messages else None
    if last is None or last.get("speaker_id") not in ("planning_expert", "dev_expert"):
        # 방어적 기본값 — 정상 흐름에서는 항상 방금 전문가 발언 직후에만 이 라우터가 불린다.
        return routed("facilitator", "missing_expert_message")
    structured = last.get("structured") or {}

    turn_count = state.get("expert_turn_count", 0)
    hit_round_cap = turn_count >= MAX_EXPERT_TURNS_PER_ROUND

    active_issue_id = state.get("active_issue_id")
    hit_issue_cap = False
    if active_issue_id:
        for issue in state.get("open_issues") or []:
            if issue["issue_id"] == active_issue_id and issue.get("turns", 0) >= MAX_EXPERT_TURNS_PER_ISSUE:
                hit_issue_cap = True
                break

    # 용준/Claude(2026-07-22, 요청: 지정 위원 질문 후 상대 검토 코드 강제) — required_counterpart_
    # speaker_id가 남아있고 아직 검토가 끝나지 않았다면(counterpart_review_completed=False),
    # issue_resolved/needs_user_input/recommended_next_speaker 등 다른 어떤 신호보다 이 검토를
    # 우선한다 — "지정 위원이 issue_resolved=true를 반환해도 상대 검토 전에는 최종 확정 금지"
    # (요청 7번)와 "counterpart_review_completed=false인 동안 facilitator 이동 금지"(요청 6번)의
    # 실제 강제 지점이다. 발언·LLM 호출 상한(요청 10번)만은 예외로 여전히 절대 우선한다 — 상한에
    # 도달했는데도 검토를 강제하면 무한 루프 방지 장치 자체가 무력화되기 때문이다.
    required_counterpart = state.get("required_counterpart_speaker_id")
    review_pending = bool(required_counterpart) and not state.get("counterpart_review_completed", True)
    if review_pending:
        if hit_round_cap or hit_issue_cap:
            return routed("facilitator", "hard_turn_cap")
        return routed(required_counterpart, "required_counterpart_review")

    if hit_round_cap:
        return routed("facilitator", "max_turns_reached")
    if structured.get("needs_user_input"):
        return routed("facilitator", "user_input_required")
    if hit_issue_cap:
        return routed("facilitator", "max_issue_turns_reached")

    if turn_count >= MIN_EXPERT_TURNS_PER_ROUND and not (state.get("open_issues") or []):
        # 열린 쟁점이 하나도 없다 — 지금까지 다룬 쟁점이 전부 해결됐다는 뜻이므로 정리한다.
        return routed("facilitator", "consensus_reached")

    recommended = structured.get("recommended_next_speaker")
    if recommended not in _VALID_NEXT_SPEAKERS:
        recommended = _DISCUSSION_COUNTERPART.get(last["speaker_id"], "ideation_facilitator")
    if recommended in ("ideation_facilitator", "user"):
        return routed("facilitator", "recommended_facilitator_or_user", recommended)
    if recommended == last["speaker_id"]:
        # 용준/Claude(2026-07-22, 실측: 실제 OpenAI 호출로 라이브 검증 중 같은 화자가 스스로를
        # 다음 발언자로 반복 추천해 3턴 연속 독백하는 사례를 확인했다) — 화자가 스스로를
        # 다음 발언자로 추천하는 것은 코드가 그대로 신뢰하지 않는다(요청: "의미 없는 독백은
        # 제한"). needs_counterpart_response 값과 무관하게 항상 상대에게 넘긴다 — 상대가
        # 정말 더 할 말이 없다고 판단하면 상대 자신의 다음 발언에서 진행자에게 넘기게 된다.
        recommended = _DISCUSSION_COUNTERPART.get(last["speaker_id"], "ideation_facilitator")
        if recommended == "ideation_facilitator":
            return routed("facilitator", "self_recommendation_without_counterpart")
        return routed(recommended, "self_recommendation_redirected", structured.get("recommended_next_speaker"))
    return routed(recommended, "validated_recommendation", recommended)


def _trace_shadow_plan_created(
    *,
    session_id: str | None,
    persona_id: str,
    plan: dict,
    retrieved_evidence_count: int,
    query: str,
    elapsed_ms: float,
) -> None:
    """용준/Claude(2026-07-23, Phase 1 "Shadow Deterministic Evidence Planner"): planner가
    만든 plan을 trace 로그 하나로 남긴다(요청: CREATED/EMPTY/INVALID 이벤트 구분). plan
    내용은 prompt/claims/grounding/routing에 전혀 영향을 주지 않는다 — 여기서 로그로만
    소비된다."""
    validation = plan.get("validation") or {"valid": True, "errors": []}
    issue = plan.get("issue") or {}
    fields = dict(
        session_id=session_id,
        speaker=persona_id,
        plan_id=plan.get("plan_id"),
        policy_version=plan.get("policy_version"),
        effective_issue_id=issue.get("issue_id"),
        effective_issue_title=issue.get("title"),
        retrieval_query_preview=sanitize_preview(query, limit=160),
        retrieved_evidence_count=retrieved_evidence_count,
        eligible_evidence_count=plan.get("eligible_evidence_count"),
        selected_evidence_count=len(plan.get("selected_evidence") or []),
        empty_plan_reason=plan.get("empty_plan_reason"),
        validation_valid=validation.get("valid"),
        validation_errors=validation.get("errors"),
        elapsed_ms=elapsed_ms,
        selected_evidence=[
            {
                "ref": item.get("ref"),
                "chunk_id": item.get("chunk_id"),
                "document_id": item.get("document_id"),
                "document_role": item.get("document_role"),
                "claim_type": item.get("claim_type"),
                "quote_preview": sanitize_preview(item.get("quote", ""), limit=160),
                "quote_start": item.get("quote_start"),
                "quote_end": item.get("quote_end"),
                "retrieval_score": item.get("retrieval_score"),
                "issue_relevance_score": item.get("issue_relevance_score"),
                "selection_reason_code": item.get("selection_reason_code"),
                "reused_in_same_issue": item.get("reused_in_same_issue"),
            }
            for item in plan.get("selected_evidence") or []
        ],
    )
    if not validation.get("valid", True):
        trace_event("IDEATION_EVIDENCE_PLAN_SHADOW_INVALID", **fields)
    elif plan.get("empty_plan_reason"):
        trace_event("IDEATION_EVIDENCE_PLAN_SHADOW_EMPTY", **fields)
    else:
        trace_event("IDEATION_EVIDENCE_PLAN_SHADOW_CREATED", **fields)


def _run_shadow_evidence_planner(
    *,
    evidence_planner: "EvidencePlanningFn | None",
    persona_id: str,
    session_id: str | None,
    effective_issue: dict[str, str],
    query: str,
    retrieved: list[dict],
    runtime_scope: dict[str, Any],
    shadow_history_map: dict[str, list[dict]],
) -> tuple[dict | None, dict[str, list[dict]], float | None]:
    """shadow planner를 호출하고(있으면), plan/갱신된 shadow_history_map/실행 소요시간(ms)을
    반환한다. 예외가 나도 회의 발언 생성 자체는 절대 막지 않는다(요청: "planner 예외: 기존
    발언 생성을 실패시키지 않고 shadow failure 로그 후 기존 흐름 진행") — 실패하면
    (None, 기존 맵, None)을 그대로 돌려준다.

    용준/Claude(2026-07-23, Phase 2 "Active Evidence Injection"): 이 함수는 shadow 로그
    전용이 아니라 planner의 유일한 호출 지점이다 — active 모드(evidence_planner.active=True)가
    함께 켜져 있어도 여기서 만든 plan을 그대로 재사용한다(요청: "active와 shadow가 동시에
    켜져도 Planner를 중복 실행하지 말 것", "한 번 생성한 plan을 shadow 기록과 active
    injection에 함께 사용할 것"). 반환된 elapsed_ms는 shadow 로그와 active/fallback 로그가
    함께 쓴다."""
    if evidence_planner is None:
        return None, shadow_history_map, None

    shadow_key = f"{persona_id}:{effective_issue['issue_id']}"
    shadow_history_items = shadow_history_map.get(shadow_key, [])
    plan_started = time.perf_counter()
    try:
        plan = evidence_planner(
            persona_id=persona_id,
            effective_issue={**effective_issue, "query": query},
            retrieved_evidence=retrieved,
            runtime_scope=runtime_scope,
            shadow_history=shadow_history_items,
        )
    except Exception:
        logger.exception(
            "[IDEATION_EVIDENCE_PLAN_SHADOW_FAILED] session_id=%s speaker=%s", session_id, persona_id
        )
        trace_event(
            "IDEATION_EVIDENCE_PLAN_SHADOW_FAILED",
            level=logging.WARNING,
            session_id=session_id,
            speaker=persona_id,
            effective_issue_id=effective_issue["issue_id"],
            effective_issue_title=effective_issue["title"],
        )
        return None, shadow_history_map, None

    elapsed_ms = round((time.perf_counter() - plan_started) * 1000, 1)
    _trace_shadow_plan_created(
        session_id=session_id,
        persona_id=persona_id,
        plan=plan,
        retrieved_evidence_count=len(retrieved),
        query=query,
        elapsed_ms=elapsed_ms,
    )

    selected_chunk_ids = [item["chunk_id"] for item in plan.get("selected_evidence") or [] if item.get("chunk_id")]
    if not selected_chunk_ids:
        return plan, shadow_history_map, elapsed_ms

    updated_items = shadow_history_items + [
        {"speaker": persona_id, "effective_issue_id": effective_issue["issue_id"], "chunk_id": chunk_id}
        for chunk_id in selected_chunk_ids
    ]
    new_shadow_history_map = dict(shadow_history_map)
    new_shadow_history_map[shadow_key] = updated_items[-_SHADOW_HISTORY_KEEP:]
    return plan, new_shadow_history_map, elapsed_ms


def _build_active_planned_evidence(plan: dict, retrieved: list[dict]) -> list[dict]:
    """용준/Claude(2026-07-23, Phase 2 "Active Evidence Injection") — plan["selected_evidence"]를
    prompt/grounding에 그대로 주입할 근거 항목으로 변환한다. 원본 청크 전체 text가 아니라
    planner가 원문 substring 검증까지 마친 quote만 담는다(요청: "Planner가 추출한 검증된
    quote를 사용"). ref/chunk_id/document_id/document_role/claim_type/quote/source(=문서명)/
    page/effective_issue_id/effective_issue_title을 함께 전달한다(요청 필드 그대로) —
    document_name/section은 claim_grounding.is_relevant_candidate의 관련성 판정 품질을
    legacy(retrieved 전체 주입) 경로와 최대한 동등하게 유지하기 위한 내부 보조 필드다(LLM
    프롬프트 지시문이 요구하는 필드 목록에는 없지만, 그 값 자체가 이번 턴에 선택된 근거의
    사실 정보라 노출해도 "선택되지 않은 evidence 노출 금지" 요구와 충돌하지 않는다)."""
    issue = plan.get("issue") or {}
    by_ref = {item.get("ref"): item for item in retrieved if isinstance(item, dict) and item.get("ref")}
    items: list[dict] = []
    for selected in plan.get("selected_evidence") or []:
        source = by_ref.get(selected.get("ref")) or {}
        items.append(
            {
                "ref": selected.get("ref"),
                "chunk_id": selected.get("chunk_id"),
                "document_id": selected.get("document_id"),
                "document_role": selected.get("document_role"),
                "claim_type": selected.get("claim_type"),
                "quote": selected.get("quote"),
                "source": source.get("document_name"),
                "page": source.get("page"),
                "effective_issue_id": issue.get("issue_id"),
                "effective_issue_title": issue.get("title"),
                "document_name": source.get("document_name"),
                "section": source.get("section"),
            }
        )
    return items


def _resolve_discussion_evidence(
    *,
    evidence_planner: "EvidencePlanningFn | None",
    shadow_plan: dict | None,
    retrieved: list[dict],
) -> tuple[list[dict], str, str | None]:
    """용준/Claude(2026-07-23, Phase 2 "Active Evidence Injection") — evidence_planner의
    active 속성(백엔드가 ENABLE_IDEATION_EVIDENCE_PLANNER_DISCUSSION일 때만 세팅,
    _evidence_planner_for 참고)이 꺼져 있으면 무조건 기존 legacy 경로(retrieved 전체)를
    그대로 돌려준다 — Phase 1 shadow 전용일 때와 완전히 동일하게 동작한다.

    active가 켜져 있으면 이번 턴 prompt/grounding에 실제로 쓸 evidence와 모드를 결정한다:
      - "fallback": planner가 기술적으로 실패했다(예외로 shadow_plan이 None이거나, plan이
        validation을 통과하지 못했다) — retrieved 전체로 되돌아간다(요청 A. "Planner 기술
        실패" 정책). 부적합한 plan을 그대로 못 믿는 것이지, "근거가 없다"는 판단 자체가
        틀렸다는 뜻이 아니므로 기존 경로가 안전하다.
      - "valid_empty": plan validation은 통과했지만 이번 쟁점에 맞는 근거가 하나도 없다고
        planner가 정상적으로 판단했다(selected_evidence=[]) — retrieved 전체로 fallback하지
        않는다(요청 B. "부적합한 근거를 다시 주입하면 Planner eligibility 정책이
        무효화되기 때문"). 빈 리스트 그대로 써서 전문가가 근거 없이(expert_judgment만)
        판단하게 한다.
      - "active": plan이 유효하고 selected_evidence가 있다 — 그 근거만 prompt/grounding에
        노출한다(선택되지 않은 evidence는 노출하지 않는다).
    """
    if evidence_planner is None or not getattr(evidence_planner, "active", False):
        return retrieved, "inactive", None
    if shadow_plan is None:
        return retrieved, "fallback", "planner_exception"
    validation = shadow_plan.get("validation") or {"valid": True, "errors": []}
    if not validation.get("valid", True):
        return retrieved, "fallback", "plan_validation_failed"
    selected = shadow_plan.get("selected_evidence") or []
    if not selected:
        return [], "valid_empty", None
    return _build_active_planned_evidence(shadow_plan, retrieved), "active", None


def _build_evidence_plan_notice(mode: str, plan: dict | None) -> str:
    """용준/Claude(2026-07-23, Phase 2 "Active Evidence Injection") — active/valid_empty
    모드일 때만 prompt에 붙일 안내문을 만든다(요청: "이번 발언이 다룰 effective_issue_id/
    title", "해당 쟁점 범위 안에서 판단할 것", "다른 쟁점으로 임의 전환하지 말 것"을 명확히
    전달). routing이나 state의 active_issue_id를 강제로 바꾸지 않는다 — prompt 지시문으로만
    범위를 좁힌다."""
    if mode not in ("active", "valid_empty") or not plan:
        return ""
    issue = plan.get("issue") or {}
    issue_id = issue.get("issue_id") or ""
    issue_title = issue.get("title") or issue_id
    if mode == "active":
        allowed_refs = [
            item.get("ref")
            for item in plan.get("selected_evidence") or []
            if isinstance(item, dict) and isinstance(item.get("ref"), str) and item.get("ref")
        ]
        allowed_refs_text = ", ".join(allowed_refs) if allowed_refs else "없음"
        return (
            f'이번 발언은 아래 [검색 근거]에 나열된 항목만 문서 근거로 인용할 수 있습니다 — '
            f"이 목록에 없는 근거를 지어내거나 가정하지 마세요. 이번 발언이 다뤄야 할 쟁점은 "
            f'effective_issue_id="{issue_id}"(제목: "{issue_title}")입니다. 이 쟁점 범위 안에서만 '
            f"판단하고, 특별한 이유 없이 다른 쟁점으로 임의 전환하지 마세요. "
            f"현재 턴에서 허용된 evidence_refs는 [{allowed_refs_text}]뿐입니다. "
            f"evidence_refs에는 이번 [검색 근거] 목록에 실제로 표시된 ref만 사용할 수 있습니다. "
            f"대화 맥락의 과거 발언에서 보았던 E번호나 chunk_id는 현재 턴의 근거가 아니므로 "
            f"절대 재사용하지 마세요."
        )
    return (
        f'이번 쟁점(effective_issue_id="{issue_id}", 제목: "{issue_title}")에는 인용할 문서 근거가 '
        f"없습니다. 문서 사실(document_fact)을 새로 만들지 말고 전문가 판단(expert_judgment)으로만 "
        f"판단하세요. 이 쟁점 범위 안에서만 판단하고 다른 쟁점으로 임의 전환하지 마세요."
    )


def _trace_active_evidence_plan(
    *,
    session_id: str | None,
    persona_id: str,
    mode: str,
    fallback_reason: str | None,
    plan: dict | None,
    retrieved_evidence_count: int,
    injected_evidence_count: int,
    elapsed_ms: float | None,
) -> None:
    """용준/Claude(2026-07-23, Phase 2 "Active Evidence Injection") — prompt 조립 직전(아직
    LLM 응답/grounding 이전)에 이번 턴의 evidence 결정을 한 이벤트로 남긴다. claim/grounding
    관련 필드는 이 시점에 존재하지 않으므로 _trace_evidence_plan_compliance(응답 이후)가
    별도로 남긴다."""
    validation = (plan or {}).get("validation") or {"valid": True, "errors": []}
    issue = (plan or {}).get("issue") or {}
    fields = dict(
        session_id=session_id,
        speaker=persona_id,
        plan_id=(plan or {}).get("plan_id"),
        effective_issue_id=issue.get("issue_id"),
        effective_issue_title=issue.get("title"),
        retrieved_evidence_count=retrieved_evidence_count,
        eligible_evidence_count=(plan or {}).get("eligible_evidence_count"),
        selected_evidence_count=len((plan or {}).get("selected_evidence") or []),
        injected_planned_evidence_count=injected_evidence_count,
        selected_refs=[item.get("ref") for item in (plan or {}).get("selected_evidence") or []],
        fallback_reason=fallback_reason,
        validation_valid=validation.get("valid"),
        validation_errors=validation.get("errors"),
        elapsed_ms=elapsed_ms,
    )
    if mode == "active":
        trace_event("IDEATION_EVIDENCE_PLAN_ACTIVE", **fields)
    elif mode == "valid_empty":
        trace_event("IDEATION_EVIDENCE_PLAN_VALID_EMPTY", **fields)
    elif mode == "fallback":
        trace_event("IDEATION_EVIDENCE_PLAN_FALLBACK", level=logging.WARNING, **fields)


def _trace_evidence_plan_compliance(
    *,
    session_id: str | None,
    persona_id: str,
    mode: str,
    plan: dict,
    raw: dict,
    grounding: dict,
    generated_issue_id: str | None,
    generated_issue_title: str | None,
) -> None:
    """용준/Claude(2026-07-23, Phase 2 "Active Evidence Injection", 요청: "쟁점 정합성" —
    Phase 1에서 issue mismatch 10% 관측) — 발언 생성·grounding이 끝난 뒤 계획된 쟁점과 실제
    생성된 쟁점을 비교하고, 선택된 근거가 실제로 claims/grounding에 쓰였는지 로그로 남긴다.
    이 로그는 기록용이다 — mismatch만으로 재생성하거나 라우팅을 바꾸지 않는다(기존
    _safe_call_structured_json/_ground_and_finalize_claims의 재시도 정책과 별개 축)."""
    issue = plan.get("issue") or {}
    selected_refs = [item.get("ref") for item in plan.get("selected_evidence") or [] if item.get("ref")]
    claim_evidence_refs = sorted(
        {
            ref
            for claim in (raw.get("claims") or [])
            if isinstance(claim, dict)
            for ref in (claim.get("evidence_refs") or [])
            if isinstance(ref, str)
        }
    )
    trace_event(
        "IDEATION_EVIDENCE_PLAN_COMPLIANCE",
        session_id=session_id,
        speaker=persona_id,
        plan_id=plan.get("plan_id"),
        mode=mode,
        effective_issue_id=issue.get("issue_id"),
        effective_issue_title=issue.get("title"),
        generated_issue_id=generated_issue_id,
        generated_issue_title=generated_issue_title,
        issue_match=(generated_issue_id is None or generated_issue_id == issue.get("issue_id")),
        selected_refs=selected_refs,
        claim_evidence_refs=claim_evidence_refs,
        used_selected_evidence=bool(set(selected_refs) & set(claim_evidence_refs)),
        claim_count=len(grounding["claims"]),
        grounded_claim_count=grounding["grounded_claim_count"],
        linked_evidence_count=grounding["linked_evidence_count"],
        linked_chunk_ids=list(grounding["linked_evidence_refs"]),
    )


def make_conv_discussion_node(
    persona_id: str,
    llm_call: LLMCall,
    evidence_lookup: EvidenceLookup | None = None,
    ground_claims: ClaimGroundingFn | None = None,
    evidence_planner: "EvidencePlanningFn | None" = None,
) -> Callable[[IdeationConvState], dict]:
    """용준/Claude(2026-07-22, 요청: 동적 전문가 회의로 개편): 기획/개발 전문가의 "발언 턴"
    노드. 예전에는 speaks_second/discussion_stage를 빌드 시점에 고정해 "기획 1회 → 개발
    1회 → [조건부] 수정 1회"만 가능했지만, 이제 discussion_stage는 매 실행마다 state로
    계산하고(_discussion_stage_for), 다음 발언자·라운드 종료는 이 노드가 아니라 그래프
    라우터(_route_next_expert_turn)와 discussion_facilitator가 맡는다 — 이 노드는 발언
    하나를 만들고 open_issues/expert_turn_count/previous_speaker만 갱신한 뒤 그대로
    반환한다(phase를 절대 바꾸지 않는다)."""

    def node(state: IdeationConvState) -> dict:
        turn_started = time.perf_counter()
        # 용준/Claude(2026-07-22, 요청: 지정 위원 질문 후 상대 검토 코드 강제) — 이번 실행이
        # (a) "잠시만" 재개로 지정된 위원의 첫 응답인지, (b) 그 응답을 검토해야 할 반대편
        # 위원의 검토 발언인지를 state만 보고 결정적으로 판별한다(LLM 판단에 맡기지 않는다).
        # forced_next_speaker는 _route_entry가 이 노드를 강제 진입시켰을 때만 남아있고
        # (실행 즉시 리셋되므로), interjection_response_message_id가 아직 비어 있으면
        # "아직 첫 응답을 기록하지 않은 지정 위원 실행"이라는 뜻이다.
        is_interjection_first_response = (
            state.get("forced_next_speaker") == persona_id
            and state.get("interjection_target_speaker_id") is not None
            and not state.get("interjection_response_message_id")
        )
        is_required_counterpart_review = (
            persona_id == state.get("required_counterpart_speaker_id")
            and not state.get("counterpart_review_completed", True)
        )
        discussion_stage = _discussion_stage_for(state, persona_id)
        responding_to_target = _responding_to_for(state, persona_id, discussion_stage)
        responding_to_message_id = responding_to_target["message_id"] if responding_to_target else None
        responding_to_speaker_id = responding_to_target["speaker_id"] if responding_to_target else None
        if responding_to_speaker_id == persona_id:
            trace_event(
                "IDEATION_SPEAKER_REFERENCE_WARNING",
                level=logging.WARNING,
                session_id=state.get("session_id"),
                speaker=persona_id,
                target=responding_to_speaker_id,
                message=responding_to_message_id,
                reason="self_responding_target",
            )
            return {"phase": "failed", "failed_node": f"discussion__{persona_id}__self_target"}
        query = _topic_query(state, persona_id)
        evidence_started = time.perf_counter()
        runtime_scope = _runtime_scope_for(state)
        trace_event(
            "IDEATION_EVIDENCE_LOOKUP_SCOPE",
            session_id=runtime_scope["session_id"],
            speaker=persona_id,
            selected_candidate_document_id=runtime_scope["selected_candidate_document_id"],
            selected_candidate_document_id_source="runtime_graph_state",
        )
        retrieved = call_evidence_lookup(evidence_lookup, persona_id, query, runtime_scope=runtime_scope)
        # 용준/Claude(2026-07-22, RAG 근거 유실 수정): evidence_lookup 자체가 None이면(use_rag
        # 미사용 세션) "검색을 아예 안 했다"는 뜻이고, evidence_lookup은 있지만 결과가 빈
        # 배열이면 "검색은 했지만 0건"이다 — 둘 다 result_count=0으로 보이지만 원인이 다르므로
        # fallback_reason으로 구분한다(요청: 검색 실패와 0건 구분).
        fallback_reason = None
        if evidence_lookup is None:
            fallback_reason = "rag_not_configured"
        elif not retrieved:
            fallback_reason = "no_search_results"
        trace_event(
            "IDEATION_EVIDENCE_LOOKUP",
            session_id=state.get("session_id"),
            speaker=persona_id,
            role="planning" if persona_id == "planning_expert" else "technology",
            project_id=getattr(evidence_lookup, "trace_project_id", None),
            top_k=getattr(evidence_lookup, "trace_top_k", None),
            issue=state.get("active_issue_id"),
            query=sanitize_preview(query, limit=160),
            retrieved_evidence_count=len(retrieved),
            fallback_reason=fallback_reason,
            chunk_ids=[item.get("chunk_id") for item in retrieved if isinstance(item, dict) and item.get("chunk_id")],
            elapsed_ms=round((time.perf_counter() - evidence_started) * 1000, 1),
        )
        # 용준/Claude(2026-07-23, Phase 1 "Shadow Deterministic Evidence Planner") — 기존
        # retrieval 직후, prompt 조립 전에 shadow planner를 실행한다(요청 순서 그대로). plan
        # 결과는 아래 prompt 조립/LLM 호출/grounding 어디에도 전달하지 않고, trace 로그
        # (_trace_shadow_plan_created)와 shadow_history_map 갱신에만 쓰인다. evidence_planner가
        # None이면(플래그 꺼짐 등) 기존과 완전히 동일하게 동작한다.
        effective_issue = resolve_effective_issue(state, persona_id)
        shadow_plan, shadow_history_map, plan_elapsed_ms = _run_shadow_evidence_planner(
            evidence_planner=evidence_planner,
            persona_id=persona_id,
            session_id=state.get("session_id"),
            effective_issue=effective_issue,
            query=query,
            retrieved=retrieved,
            runtime_scope=runtime_scope,
            shadow_history_map=state.get("evidence_plan_shadow_history") or {},
        )
        # 용준/Claude(2026-07-23, Phase 2 "Active Evidence Injection") — 위에서 만든 plan을
        # 다시 실행하지 않고 그대로 재사용해 이번 턴 prompt/grounding에 쓸 evidence를
        # 결정한다. evidence_planner.active가 꺼져 있으면(기본값, 또는 shadow 전용) 항상
        # evidence_mode="inactive"이고 turn_evidence는 retrieved 그대로다 — 기존 동작과 100%
        # 동일하다.
        turn_evidence, evidence_mode, evidence_fallback_reason = _resolve_discussion_evidence(
            evidence_planner=evidence_planner,
            shadow_plan=shadow_plan,
            retrieved=retrieved,
        )
        if evidence_mode != "inactive":
            _trace_active_evidence_plan(
                session_id=state.get("session_id"),
                persona_id=persona_id,
                mode=evidence_mode,
                fallback_reason=evidence_fallback_reason,
                plan=shadow_plan,
                retrieved_evidence_count=len(retrieved),
                injected_evidence_count=len(turn_evidence),
                elapsed_ms=plan_elapsed_ms,
            )
        evidence_plan_notice = _build_evidence_plan_notice(evidence_mode, shadow_plan)
        context = conversation_context_for(state)
        if evidence_mode in ("active", "valid_empty"):
            context = _isolate_discussion_evidence_context(context)
        speaker_name, _ = _speaker_fields(persona_id)
        responding_name = _EXPERT_ROLE_LABELS.get(responding_to_speaker_id or "", responding_to_speaker_id)
        message_id = _new_message_id()
        trace_event(
            "IDEATION_TURN_START",
            session_id=state.get("session_id"),
            phase=state.get("phase"),
            round=state.get("round"),
            issue=state.get("active_issue_id"),
            speaker=persona_id,
            speaker_name=speaker_name,
            message=message_id,
            target=responding_to_speaker_id,
            target_name=responding_name,
            responding_to_message=responding_to_message_id,
            responding_to_preview=sanitize_preview(
                responding_to_target.get("content") if responding_to_target else "", limit=200
            ),
            # retrieved_evidence_count: RAG 검색으로 찾아 이번 프롬프트에 주입할 근거 수
            # (아래 build_ideation_conv_discussion_prompt 호출에 retrieved 그대로 전달).
            retrieved_evidence_count=len(retrieved),
            fallback_reason=fallback_reason,
        )
        prompt = build_ideation_conv_discussion_prompt(
            persona_id,
            state["notice_and_criteria"],
            state["user_idea"],
            turn_evidence,
            context,
            speaks_second=(discussion_stage == "response"),
            discussion_stage=discussion_stage,
            active_issue_id=state.get("active_issue_id"),
            open_issues=state.get("open_issues") or [],
            resolved_issues=state.get("resolved_issues") or [],
            current_speaker={"speaker_id": persona_id, "role_name": speaker_name},
            responding_to_message=(
                {
                    "speaker_id": responding_to_speaker_id,
                    "role_name": responding_name,
                    "message_id": responding_to_message_id,
                    "spoken_text": responding_to_target.get("content", ""),
                }
                if responding_to_target
                else {}
            ),
            evidence_plan_notice=evidence_plan_notice,
        )
        validate = lambda raw, _stage=discussion_stage: _validate_discussion_response(  # noqa: E731
            raw,
            _stage,
            current_speaker_id=persona_id,
            responding_to_speaker_id=responding_to_speaker_id,
            responding_to_content=(responding_to_target.get("content") if responding_to_target else None),
        )
        raw, ok, attempts = _safe_call_structured_json(llm_call, prompt, validate, f"discussion__{persona_id}")
        used = state.get("llm_calls_used", 0) + attempts
        if not ok:
            raw = _safe_discussion_fallback(
                persona_id=persona_id,
                state=state,
                discussion_stage=discussion_stage,
                responding_to_message_id=responding_to_message_id,
                responding_to_content=(responding_to_target.get("content") if responding_to_target else None),
            )
            trace_event(
                "IDEATION_STRUCTURED_RESPONSE_SAFE_FALLBACK",
                session_id=state.get("session_id"),
                node=f"discussion__{persona_id}",
                attempts=attempts,
                speaker=persona_id,
                issue=raw["active_issue_id"],
                next_speaker=raw["recommended_next_speaker"],
                claim_type="expert_judgment",
            )

        raw, grounding, used = _ground_and_finalize_claims(
            persona_id=persona_id,
            raw=raw,
            retrieved=turn_evidence,
            prompt=prompt,
            llm_call=llm_call,
            validate=validate,
            used=used,
            ground_claims_fn=ground_claims,
        )

        stance = raw.get("stance")
        if stance not in _VALID_DISCUSSION_STANCES:
            stance = "보완"
        message_type = _STANCE_TO_MESSAGE_TYPE.get(stance, "opinion")

        known_ids = {m["message_id"] for m in state["messages"]}
        judgment = raw.get("judgment", "")
        reason = raw.get("reason", "")
        suggestion = raw.get("suggestion", "")
        interim_conclusion = raw.get("interim_conclusion", "")
        responding_to = raw.get("responding_to") or None
        agreement = raw.get("agreement") or None
        concern = raw.get("concern") or None
        revision_text = raw.get("revision") or None
        confirmed_items = _as_string_list(raw.get("confirmed"))
        unconfirmed_items = _as_string_list(raw.get("unconfirmed"))

        # 상호참조는 LLM 호출 전에 코드가 결정하고 프롬프트/검증/저장에 같은 값을 쓴다.
        referenced_ids_raw = list(raw.get("referenced_message_ids") or [])
        if responding_to_message_id and responding_to_message_id not in referenced_ids_raw:
            referenced_ids_raw.append(responding_to_message_id)

        # 용준/Claude(2026-07-22, 요청: 동적 전문가 회의로 개편) — 다음 발언자/쟁점 판단
        # 필드. recommended_next_speaker는 여기서 정규화만 하고, 실제 라우팅 검증은
        # _route_next_expert_turn(그래프 라우터)이 한다(LLM 추천을 그대로 신뢰하지 않는다).
        generated_issue_id_raw = (raw.get("active_issue_id") or "").strip() or None
        generated_issue_title_raw = (raw.get("active_issue_title") or "").strip() or None
        if shadow_plan is not None and generated_issue_id_raw is not None:
            # 용준/Claude(2026-07-23, Phase 1 "Shadow Deterministic Evidence Planner", 요청:
            # 첫 턴 issue mismatch rate 측정) — retrieval이 실제로 겨냥한 쟁점(effective_issue)과
            # LLM이 자체적으로 반환한 쟁점(generated_issue_id_raw)이 다르면 로그만 남긴다.
            # mismatch가 발생해도 발언을 재생성하거나 라우팅을 바꾸지 않는다(Phase 1 범위 밖).
            if generated_issue_id_raw != shadow_plan["issue"]["issue_id"]:
                trace_event(
                    "IDEATION_EVIDENCE_PLAN_SHADOW_ISSUE_MISMATCH",
                    session_id=state.get("session_id"),
                    speaker=persona_id,
                    plan_id=shadow_plan.get("plan_id"),
                    effective_issue_id=shadow_plan["issue"]["issue_id"],
                    effective_issue_title=shadow_plan["issue"]["title"],
                    generated_issue_id=generated_issue_id_raw,
                    generated_issue_title=generated_issue_title_raw,
                    issue_match=False,
                )
        # 용준/Claude(2026-07-23, Phase 2 "Active Evidence Injection", 요청: "쟁점 정합성"
        # compliance 로그) — evidence_mode가 "inactive"가 아닐 때만(discussion 플래그가 켜져
        # planner를 실제로 참고한 턴에만) 남긴다. mismatch/미사용이 확인돼도 여기서 발언을
        # 재생성하거나 라우팅을 바꾸지 않는다 — 순수 기록이다.
        if evidence_mode != "inactive" and shadow_plan is not None:
            _trace_evidence_plan_compliance(
                session_id=state.get("session_id"),
                persona_id=persona_id,
                mode=evidence_mode,
                plan=shadow_plan,
                raw=raw,
                grounding=grounding,
                generated_issue_id=generated_issue_id_raw,
                generated_issue_title=generated_issue_title_raw,
            )
        active_issue_id = generated_issue_id_raw or _fallback_issue_id(state)
        active_issue_title = generated_issue_title_raw or active_issue_id
        new_information = _as_string_list(raw.get("new_information"))
        proposal = raw.get("proposal") or None
        changed_position = bool(raw.get("changed_position"))
        needs_counterpart_response = raw.get("needs_counterpart_response")
        needs_counterpart_response = True if needs_counterpart_response is None else bool(needs_counterpart_response)
        recommended_next_speaker = raw.get("recommended_next_speaker")
        if recommended_next_speaker not in _VALID_NEXT_SPEAKERS:
            recommended_next_speaker = _DISCUSSION_COUNTERPART.get(persona_id, "ideation_facilitator")
        issue_resolved = bool(raw.get("issue_resolved"))
        # 용준/Claude(2026-07-22, 요청 7번: "첫 답변자가 issue_resolved=true를 반환해도 상대
        # 검토 전에는 최종 resolved로 확정 금지") — 지정 위원의 첫 응답 자신이 이 쟁점을
        # 해결됐다고 판단해도, 코드가 강제로 open 상태를 유지한다(active_issue_id도 아래에서
        # 계속 살아있게 된다) — 상대가 검토한 뒤 자신도 issue_resolved=true를 반환해야만 실제로
        # resolved_issues로 옮겨간다. 이 override는 message 생성 이전에 적용되므로
        # structured["issue_resolved"]도 함께 False로 기록된다(화면/로그가 "아직 미확정"이라는
        # 실제 상태와 다른 값을 보여주지 않도록 하기 위함 — raw 원본 값을 숨기는 것이 목적이
        # 아니라, "이 시점에 회의가 실제로 이 쟁점을 닫았는가"를 정확히 반영하려는 것이다).
        if is_interjection_first_response and issue_resolved:
            issue_resolved = False
        needs_user_input = bool(raw.get("needs_user_input"))
        user_question = (raw.get("user_question") or None) if needs_user_input else None
        # 용준/Claude(2026-07-22, 요청 9번: 반복 회의 방지) — 이번 발언의 핵심 문서 주장이
        # 재생성 후에도 근거 연결에 실패했는데(evidence_status="ungrounded") LLM 스스로
        # 사용자 질문으로 전환하지 않았다면, 전문가끼리 같은 내용을 계속 반복하지 않도록
        # 코드가 강제로 사용자에게 되묻는 흐름으로 전환한다.
        if grounding["evidence_status"] == "ungrounded" and not needs_user_input:
            needs_user_input = True
            if grounding["missing_information"]:
                user_question = (
                    "현재 자료에서는 "
                    + " · ".join(grounding["missing_information"][:2])
                    + " 부분을 확인할 수 없습니다. 관련 정보를 알고 계신가요?"
                )
            else:
                user_question = "이 부분을 판단할 근거 자료가 부족합니다. 관련 정보를 제공해 주실 수 있나요?"
            recommended_next_speaker = "user"

        # 용준/Claude(2026-07-22, 요청: 반복되는 근거 없는 의견을 사용자 질문으로 전환) —
        # evidence_status="ungrounded"(document_fact 인용 실패, 위에서 즉시 처리됨) 외에도
        # linked_evidence_count=0인 턴이나 expert_judgment_only 상태, 같은 missing_information이
        # 별다른 진전 없이 "쟁점이 바뀌지 않은 채" 반복되면(2회 연속) 전문가 둘이서 끝없이 같은
        # 판단을 되풀이하는 대신 사용자에게 구체적으로 되묻는다(요청 4번).
        #
        # ground_claims_fn이 없으면(use_rag=False 등 RAG 자체를 쓰지 않는 세션) grounding은
        # 항상 _EMPTY_GROUNDING(linked_evidence_count=0)이다 — 이건 "근거 연결이 반복 실패"가
        # 아니라 "애초에 RAG를 검증하지 않기로 한 세션"이므로, 이 반복 감지 자체를 건너뛴다
        # (그렇지 않으면 RAG 미사용 세션마다 두 번째 발언에서 곧바로 사용자에게 되묻게 된다).
        #
        # new_information(발언 스키마 필수 필드)의 어휘 반복 여부는 로그로만 남기고(같은
        # 화자가 라운드마다 정형화된 문구를 쓰는 정상적인 경우까지 오탐하기 쉬워 라우팅
        # 트리거로 쓰지 않는다) 사용자 전환 조건에서는 제외한다.
        ground_claims_configured = ground_claims is not None
        issue_changed = active_issue_id != state.get("active_issue_id")
        missing_info_normalized = sorted({m.strip() for m in grounding["missing_information"] if m and m.strip()})
        new_information_text = " ".join(new_information)

        if not ground_claims_configured:
            consecutive_zero_linked_turns = 0
            consecutive_expert_judgment_only_turns = 0
            consecutive_repeated_missing_information_turns = 0
            consecutive_no_new_information_turns = 0
        elif issue_changed:
            zero_linked_turn = grounding["linked_evidence_count"] == 0
            consecutive_zero_linked_turns = 1 if zero_linked_turn else 0
            expert_judgment_only_turn = grounding["evidence_status"] == "expert_judgment_only"
            consecutive_expert_judgment_only_turns = 1 if expert_judgment_only_turn else 0
            consecutive_repeated_missing_information_turns = 0
            consecutive_no_new_information_turns = 0
        else:
            prev_zero_linked = state.get("consecutive_zero_linked_turns", 0)
            prev_expert_judgment_only = state.get("consecutive_expert_judgment_only_turns", 0)
            prev_missing_streak = state.get("consecutive_repeated_missing_information_turns", 0)
            prev_no_new_info_streak = state.get("consecutive_no_new_information_turns", 0)
            prev_missing_information = state.get("last_missing_information", [])
            prev_new_information_text = state.get("last_new_information_text", "")

            zero_linked_turn = grounding["linked_evidence_count"] == 0
            consecutive_zero_linked_turns = prev_zero_linked + 1 if zero_linked_turn else 0
            expert_judgment_only_turn = grounding["evidence_status"] == "expert_judgment_only"
            consecutive_expert_judgment_only_turns = prev_expert_judgment_only + 1 if expert_judgment_only_turn else 0
            missing_information_repeated = (
                bool(missing_info_normalized) and missing_info_normalized == prev_missing_information
            )
            consecutive_repeated_missing_information_turns = prev_missing_streak + 1 if missing_information_repeated else 0
            no_new_information_turn = bool(prev_new_information_text) and _looks_like_restatement(
                new_information_text, prev_new_information_text
            )
            consecutive_no_new_information_turns = prev_no_new_info_streak + 1 if no_new_information_turn else 0

        _REPETITION_TURN_THRESHOLD = 2
        repetition_triggered = ground_claims_configured and (
            consecutive_zero_linked_turns >= _REPETITION_TURN_THRESHOLD
            or consecutive_expert_judgment_only_turns >= _REPETITION_TURN_THRESHOLD
            or consecutive_repeated_missing_information_turns >= _REPETITION_TURN_THRESHOLD
        )
        if repetition_triggered and not needs_user_input:
            needs_user_input = True
            if missing_info_normalized:
                user_question = (
                    "현재 자료에서는 " + " · ".join(missing_info_normalized[:2])
                    + " 부분을 확인할 수 없습니다. 관련 정보를 알고 계신가요?"
                )
            else:
                user_question = (
                    "같은 전문가 판단이 반복되고 있어 더 진전이 없습니다. "
                    "판단에 필요한 구체적인 정보를 제공해 주실 수 있나요?"
                )
            recommended_next_speaker = "user"
        next_action = "await_user_input" if needs_user_input else "continue_discussion"

        content = _compose_discussion_content(raw.get("spoken_text", ""))
        message = _build_message(
            persona_id=persona_id,
            round_number=state["round"],
            message_type=message_type,
            content=content,
            referenced_message_ids=_referenced_ids(referenced_ids_raw, known_ids),
            # 용준/Claude(2026-07-22, RAG 근거 유실 수정): make_conv_question_node와 동일한
            # 이유로 raw.get("evidence") 대신 retrieved(이번 턴 RAG 검색 결과, 프롬프트에
            # 이미 주입됨)를 그대로 저장한다.
            evidence=retrieved,
            grounding=grounding,
            # 용준/Claude(2026-07-21, 프런트 상세보기): content(위)는 하위 호환을 위해 그대로
            # 유지하고, 필드별 구조를 선택 정보로 추가한다 — 프런트가 판단/제안만 기본 노출하고
            # 근거/확정/미확정을 "상세 보기"로 접을 수 있게 한다(요청 9번). content를 대체하는
            # 것이 아니라 순수 추가다.
            structured={
                "judgment": judgment,
                "reason": reason,
                "suggestion": suggestion,
                "interim_conclusion": interim_conclusion,
                "responding_to": responding_to,
                "agreement": agreement,
                "concern": concern,
                "revision": revision_text,
                "confirmed": confirmed_items,
                "unconfirmed": unconfirmed_items,
                "responding_to_message_id": responding_to_message_id,
                "responding_to_speaker_id": responding_to_speaker_id,
                # 용준/Claude(2026-07-22, 요청: 동적 전문가 회의로 개편) — 다음 발언자/쟁점
                # 판단 근거. _route_next_expert_turn과 "잠시만" 재개(reply_to_interjection)가
                # 그대로 참조한다.
                "active_issue_id": active_issue_id,
                "active_issue_title": active_issue_title,
                "new_information": new_information,
                "proposal": proposal,
                "changed_position": changed_position,
                "needs_counterpart_response": needs_counterpart_response,
                "recommended_next_speaker": recommended_next_speaker,
                "issue_resolved": issue_resolved,
                "needs_user_input": needs_user_input,
                "user_question": user_question,
                # 용준/Claude(2026-07-22, 요청: 반복 방지 결과를 로그·다음 라우팅이 참조할 수
                # 있게 명시적으로 남긴다) — needs_user_input과 항상 일치하는 파생값이지만,
                # "왜 지금 사용자에게 넘기는지"를 별도 필드로 노출해 로그에서 바로 읽을 수 있다.
                "next_action": next_action,
                # 용준/Claude(2026-07-22, 요청: 진행자가 검증된 주장만 사실로 요약하도록
                # 제한) — discussion_facilitator 프롬프트는 planning_position/
                # development_review를 이 dict 그대로 JSON 직렬화해 받는다(prompt_loader.py
                # build_ideation_conv_discussion_facilitator_prompt). evidence_status/
                # unsupported_claims를 함께 넘겨 진행자가 "문서로 확인된 내용"과 "근거가
                # 부족한 내용"을 구분해서 정리하도록 한다 — 검증 안 된 주장을 새 사실처럼
                # 정리하지 못하게 막는 1차 방어선(2차는 아래 프롬프트 지시문).
                "evidence_status": grounding["evidence_status"],
                "linked_evidence_refs": grounding["linked_evidence_refs"],
                "unsupported_claims": [c["text"] for c in grounding["unsupported_claims"]],
                "missing_information": grounding["missing_information"],
                # 서버가 만든 구조화 실패 복구 메시지인지 감사·재현 시 구분한다.
                "safe_fallback": bool(raw.get("safe_fallback")),
                "safe_fallback_reason": raw.get("safe_fallback_reason"),
            },
            message_id=message_id,
        )
        trace_event(
            "IDEATION_TURN_END",
            session_id=state.get("session_id"),
            message=message["message_id"],
            speaker=persona_id,
            target=responding_to_speaker_id,
            issue=active_issue_id,
            stance=stance,
            resolved=issue_resolved,
            needs_counterpart=needs_counterpart_response,
            recommended_next=recommended_next_speaker,
            new_information_count=len(new_information),
            text_length=len(content),
            text=sanitize_preview(content),
            # injected_evidence_count: 실제로 이번 prompt에 담겨 나간 근거 수. evidence_mode가
            # "inactive"(기존 legacy 경로)면 위 IDEATION_TURN_START의 retrieved_evidence_count와
            # 항상 같다 — turn_evidence가 retrieved 그대로이기 때문이다. Phase 2 active 모드
            # (evidence_mode="active"/"valid_empty")에서는 이보다 작을 수 있다(요청: 선택되지
            # 않은 evidence는 prompt에 넣지 않는다) — message["evidence"]는 검색·감사 기록
            # 용도로 항상 retrieved 전체를 유지하므로(기존 계약 그대로) 여기서는 그 값 대신
            # turn_evidence 길이를 쓴다.
            injected_evidence_count=len(turn_evidence),
            # 용준/Claude(2026-07-22, 요청: RAG 근거 실제 활용 강화) — 성공 판단 기준은
            # injected_evidence_count가 아니라 linked_evidence_count다(요청 18번).
            linked_evidence_count=grounding["linked_evidence_count"],
            supported_claim_count=grounding["supported_claim_count"],
            unsupported_claim_count=grounding["unsupported_claim_count"],
            accepted_claim_count=grounding["accepted_claim_count"],
            grounded_claim_count=grounding["grounded_claim_count"],
            expert_judgment_count=grounding["expert_judgment_count"],
            evidence_status=grounding["evidence_status"],
            missing_information=grounding["missing_information"],
            consecutive_zero_linked_turns=consecutive_zero_linked_turns,
            consecutive_expert_judgment_only_turns=consecutive_expert_judgment_only_turns,
            consecutive_repeated_missing_information_turns=consecutive_repeated_missing_information_turns,
            consecutive_no_new_information_turns=consecutive_no_new_information_turns,
            next_action=next_action,
            elapsed_ms=round((time.perf_counter() - turn_started) * 1000, 1),
        )

        new_consensus = list(state["consensus"])
        for item in _as_string_list(raw.get("confirmed")):
            if item not in new_consensus:
                new_consensus.append(item)

        previous_open_ids = {issue.get("issue_id") for issue in (state.get("open_issues") or [])}
        previous_resolved_ids = {issue.get("issue_id") for issue in (state.get("resolved_issues") or [])}
        open_issues, resolved_issues = _update_issue_records(
            open_issues=state.get("open_issues") or [],
            resolved_issues=state.get("resolved_issues") or [],
            persona_id=persona_id,
            issue_id=active_issue_id,
            issue_title=active_issue_title,
            position_text=proposal or interim_conclusion or judgment,
            resolved=issue_resolved,
            resolution_text=proposal or interim_conclusion or judgment,
        )
        if active_issue_id not in previous_open_ids and not issue_resolved:
            trace_event(
                "IDEATION_ISSUE_OPENED",
                session_id=state.get("session_id"),
                issue=active_issue_id,
                title=active_issue_title,
                updated_by=persona_id,
                previous_status="missing",
                new_status="open",
                remaining_open_issue_count=len(open_issues),
            )
        elif issue_resolved and active_issue_id not in previous_resolved_ids:
            trace_event(
                "IDEATION_ISSUE_RESOLVED",
                session_id=state.get("session_id"),
                issue=active_issue_id,
                title=active_issue_title,
                updated_by=persona_id,
                previous_status="open",
                new_status="resolved",
                resolution=sanitize_preview(proposal or interim_conclusion or judgment, limit=200),
                remaining_open_issue_count=len(open_issues),
            )
        else:
            trace_event(
                "IDEATION_ISSUE_UPDATED",
                session_id=state.get("session_id"),
                issue=active_issue_id,
                title=active_issue_title,
                updated_by=persona_id,
                previous_status="open",
                new_status="open",
                remaining_open_issue_count=len(open_issues),
            )

        unconfirmed = _as_string_list(raw.get("unconfirmed"))
        update: dict[str, Any] = {
            "messages": [message],
            "consensus": new_consensus,
            # "unconfirmed" 키 자체가 없으면(구버전 응답 등) 기존 unresolved_issues를 그대로
            # 둔다 — 키가 있는데 배열이 아니면(타입 오류) 안전하게 빈 배열로 정규화한다.
            "unresolved_issues": unconfirmed if "unconfirmed" in raw else state["unresolved_issues"],
            "llm_calls_used": used,
            "open_issues": open_issues,
            "resolved_issues": resolved_issues,
            "active_issue_id": None if issue_resolved else active_issue_id,
            "previous_speaker": persona_id,
            "expert_turn_count": state.get("expert_turn_count", 0) + 1,
            # "잠시만" 재개(reply_to_interjection)가 강제 지정한 다음 발언자는 실행 즉시
            # 소비된다 — 어느 전문가 노드가 실행되든(강제 지정 대상이든 아니든) 매 턴마다
            # None으로 리셋해 다음 라운드에 잔류하지 않게 한다.
            "forced_next_speaker": None,
            # 용준/Claude(2026-07-22, 요청: "잠시만" 취소 중 phase 오염 수정) — discussion_
            # facilitator/candidate_selection이 남긴 next_route("continue_round"/
            # "to_refinement")는 이 노드(그 라우팅의 목적지)가 실행되는 순간 소비 완료다 —
            # forced_next_speaker와 같은 이유로 다음 라운드/다음 요청에 잔류하지 않게 리셋한다.
            "next_route": None,
            # 용준/Claude(2026-07-22, 요청: 반복되는 근거 없는 의견을 사용자 질문으로 전환) —
            # 다음 턴이 이어서 참조할 반복 감지 카운터. apply_user_answer가 사용자 답변 시점에
            # 0/빈 값으로 리셋한다(ideation_conv_state.py 참고).
            "consecutive_zero_linked_turns": consecutive_zero_linked_turns,
            "consecutive_expert_judgment_only_turns": consecutive_expert_judgment_only_turns,
            "last_missing_information": missing_info_normalized,
            "consecutive_repeated_missing_information_turns": consecutive_repeated_missing_information_turns,
            "last_new_information_text": new_information_text,
            "consecutive_no_new_information_turns": consecutive_no_new_information_turns,
            # 용준/Claude(2026-07-23, Phase 1 "Shadow Deterministic Evidence Planner") — 다음
            # 턴이 이어서 참조할 shadow 선택 이력(세션 범위 state, API 응답에는 노출하지 않는다).
            # evidence_planner가 주입되지 않았으면(기본값) 이 필드는 항상 기존 값 그대로다.
            "evidence_plan_shadow_history": shadow_history_map,
        }
        if is_interjection_first_response:
            # 용준/Claude(2026-07-22, 요청: 지정 위원 질문 후 상대 검토 코드 강제) — "검토
            # 대상"을 이 메시지로 확정한다. required_counterpart_speaker_id/
            # counterpart_review_completed는 reply_to_interjection이 이미 설정해 둔 값
            # 그대로 유지한다(여기서는 아직 검토가 끝나지 않았으므로 바꾸지 않는다).
            update["interjection_response_message_id"] = message["message_id"]
        if is_required_counterpart_review:
            # 상대 위원이 실제로 검토를 마쳤다 — 이 인터젝션에 대한 강제 라우팅을 여기서
            # 종료한다(요청 9번: "상대 검토가 끝난 뒤에만 facilitator 또는 다음 쟁점으로
            # 이동"). 네 필드를 한 세트로 리셋해 다음 인터젝션과 섞이지 않게 한다.
            update["counterpart_review_completed"] = True
            update["interjection_target_speaker_id"] = None
            update["interjection_response_message_id"] = None
            update["required_counterpart_speaker_id"] = None
        return update

    return node


def _stop_reason_for(state: IdeationConvState) -> str:
    """용준/Claude(2026-07-22, 요청: 동적 전문가 회의로 개편): _route_next_expert_turn이
    "facilitator"로 라우팅한 이유를 다시 계산한다(라우터와 같은 우선순위) — 진행자 프롬프트와
    stop_reason 저장에 쓴다. 라우팅 자체를 바꾸지 않는 순수 조회 함수다."""
    messages = state["messages"]
    last = messages[-1] if messages else None
    structured = (last.get("structured") or {}) if last else {}
    if structured.get("needs_user_input"):
        return "user_input_required"
    if state.get("expert_turn_count", 0) >= MAX_EXPERT_TURNS_PER_ROUND:
        return "max_turns_reached"
    active_issue_id = state.get("active_issue_id")
    if active_issue_id:
        for issue in state.get("open_issues") or []:
            if issue["issue_id"] == active_issue_id and issue.get("turns", 0) >= MAX_EXPERT_TURNS_PER_ISSUE:
                return "max_turns_reached"
    if not (state.get("open_issues") or []):
        return "consensus_reached"
    return "no_new_information"


def make_discussion_facilitator_node(llm_call: LLMCall) -> Callable[[IdeationConvState], dict]:
    """용준/Claude(2026-07-22, 요청: 동적 전문가 회의로 개편): 예전에는 기획/개발이 각각
    정확히 1회씩 말한 "매 라운드 끝"에 무조건 실행됐지만, 이제 _route_next_expert_turn이
    쟁점·반론·발언 캡에 따라 실제로 라운드가 끝났다고 판단했을 때만 실행된다(전문가가
    needs_user_input로 신호를 주거나, 열린 쟁점이 모두 해결되거나, 발언 캡에 도달했을
    때). 다음 라운드로 자동 진행할지(continue_round) 사용자 결정을 기다릴지
    (await_user_decision)는 이제 전문가 노드가 아니라 이 노드가 직접 결정한다 — 그 판단은
    항상 round/max_rounds 상한(무한 루프 방지)과 stop_reason을 코드가 먼저 검증한 뒤에만
    LLM이 정리 문장을 만든다."""

    def node(state: IdeationConvState) -> dict:
        turn_started = time.perf_counter()
        stop_reason = _stop_reason_for(state)
        round_number = state["round"]
        max_rounds = state["max_rounds"]
        open_issues = state.get("open_issues") or []

        if stop_reason == "user_input_required":
            decided_next_action = "await_user_decision"
        elif round_number >= max_rounds:
            decided_next_action = "await_user_decision"
        elif stop_reason == "max_turns_reached" and open_issues:
            decided_next_action = "continue_round"
        elif stop_reason == "consensus_reached" and not open_issues:
            decided_next_action = "await_user_decision"
        else:
            decided_next_action = "continue_round"

        planning_msg = _most_recent_message_by(state["messages"], "planning_expert")
        dev_msg = _most_recent_message_by(state["messages"], "dev_expert")
        planning_position = planning_msg.get("structured") if planning_msg else None
        development_review = dev_msg.get("structured") if dev_msg else None
        message_id = _new_message_id()
        trace_event(
            "IDEATION_TURN_START",
            session_id=state.get("session_id"),
            message=message_id,
            phase=state.get("phase"),
            round=round_number,
            issue=state.get("active_issue_id"),
            speaker="ideation_facilitator",
            speaker_name="진행자",
            evidence_count=0,
        )

        prompt = build_ideation_conv_discussion_facilitator_prompt(
            state["notice_and_criteria"],
            planning_position,
            development_review,
            None,
            state["consensus"],
            state["unresolved_issues"],
            decided_next_action,
            round_number,
            max_rounds,
            open_issues=open_issues,
            resolved_issues=state.get("resolved_issues") or [],
            stop_reason=stop_reason,
        )
        raw, ok, attempts = _safe_call_structured_json(
            llm_call, prompt, _validate_facilitator_response, "discussion_facilitator"
        )
        used = state.get("llm_calls_used", 0) + attempts
        if not ok:
            return {"phase": "failed", "failed_node": "discussion_facilitator", "llm_calls_used": used}

        summary_text = raw.get("facilitator_summary", "")
        agreements = _as_string_list(raw.get("agreements"))
        disagreements = _as_string_list(raw.get("disagreements"))
        needs_user_decision = bool(raw.get("needs_user_decision"))
        user_question = raw.get("user_question") if needs_user_decision else None
        # 용준/Claude(2026-07-22, 요청: 보고서형 메시지 → 자연스러운 회의 발화 전환) — 채팅에
        # 실제로 보이는 content는 spoken_text(1~2문장의 자연스러운 정리, needs_user_decision=
        # true면 질문 자체를 자연스럽게 포함) 그대로다.
        content = raw.get("spoken_text", "").strip()

        message = _build_message(
            persona_id="ideation_facilitator",
            round_number=round_number,
            message_type="summary",
            content=content,
            referenced_message_ids=[],
            evidence=[],
            structured={
                "facilitator_summary": summary_text,
                "agreements": agreements,
                "disagreements": disagreements,
                "needs_user_decision": needs_user_decision,
                "user_question": user_question,
                "stop_reason": stop_reason,
            },
            message_id=message_id,
        )
        trace_event(
            "IDEATION_TURN_END",
            session_id=state.get("session_id"),
            message=message["message_id"],
            speaker="ideation_facilitator",
            phase=state.get("phase"),
            round=round_number,
            stop_reason=stop_reason,
            next_action=decided_next_action,
            text_length=len(content),
            text=sanitize_preview(content),
            elapsed_ms=round((time.perf_counter() - turn_started) * 1000, 1),
        )

        new_consensus = list(state["consensus"])
        for item in agreements:
            if item not in new_consensus:
                new_consensus.append(item)

        def _snapshot(persona_id: str, raw_or_none: dict | None) -> str:
            if not raw_or_none:
                return ""
            return _discussion_round_snapshot_text(
                persona_id,
                raw_or_none.get("judgment", ""),
                raw_or_none.get("reason", ""),
                raw_or_none.get("suggestion", ""),
                raw_or_none.get("confirmed"),
                raw_or_none.get("unconfirmed"),
                raw_or_none.get("interim_conclusion", ""),
                raw_or_none.get("responding_to"),
                raw_or_none.get("agreement"),
                raw_or_none.get("concern"),
                raw_or_none.get("revision"),
            )

        record = DiscussionRoundRecord(
            round=round_number,
            planning_position=_snapshot("planning_expert", planning_position),
            development_review=_snapshot("dev_expert", development_review),
            revised_proposal=None,
            facilitator_summary=summary_text,
            needs_user_decision=needs_user_decision,
        )

        update: dict[str, Any] = {
            "messages": [message],
            "consensus": new_consensus,
            "discussion_rounds": [record],
            "llm_calls_used": used,
            "stop_reason": stop_reason,
        }
        if decided_next_action == "continue_round":
            # 용준/Claude(2026-07-22, 요청: "잠시만" 취소 중 phase 오염 수정) — 다음 라운드로
            # 자동 진행한다(같은 그래프 호출 안에서, 사용자 입력 없이). phase는 항상 이 시점의
            # 실제 canonical 상태("expert_discussion", 이미 REPLYABLE/진입 가능한 값)로
            # 유지하고, "다음 라운드 전문가 노드로 곧장 이어간다"는 그래프 내부 라우팅
            # 신호는 next_route에 별도로 담는다(ideation_conv_build.py::_route_after_facilitator
            # 참고) — phase 자체를 그래프 밖에서는 의미 없는 내부 신호값으로 잠깐 바꾸던
            # 이전 방식은, 바로 이 시점(다음 노드 실행 중)에 취소되면 그 "잠깐"의 phase가
            # 그대로 세션에 저장돼 재개를 막는 문제가 있었다. 열린 쟁점(있다면)은 다음
            # 라운드에도 그대로 이어간다 — expert_turn_count만 리셋해 새 라운드의 발언 캡을
            # 다시 확보한다.
            update["phase"] = "expert_discussion"
            update["next_route"] = "continue_round"
            update["round"] = round_number + 1
            update["expert_turn_count"] = 0
            update["pending_question"] = None
            update["pending_question_topic"] = None
        elif needs_user_decision and user_question:
            update["phase"] = "awaiting_user_decision"
            update["next_route"] = None
            update["pending_question"] = user_question
            update["pending_question_topic"] = "facilitator_decision"
        else:
            update["phase"] = "awaiting_user_decision"
            update["next_route"] = None
            update["pending_question"] = None
            update["pending_question_topic"] = None
        return update

    return node


def _validate_canvas_response(raw: dict) -> str | None:
    """캔버스 응답의 키와 타입을 검증한다. 논의 전 빈 문자열은 허용한다."""
    for key in _CANVAS_TEXT_FIELDS:
        if not isinstance(raw.get(key), str):
            return f"missing_or_not_string:{key}"
    feasibility = raw.get("feasibility")
    if not isinstance(feasibility, str) or feasibility.strip() not in _VALID_CANVAS_FEASIBILITY:
        return "invalid_feasibility"
    if not isinstance(raw.get("risks"), list):
        return "risks_not_a_list"
    return None


def make_canvas_update_node(llm_call: LLMCall) -> Callable[[IdeationConvState], dict]:
    """라운드 종료 뒤 캔버스를 갱신한다. 실패해도 회의 상태는 실패로 바꾸지 않는다."""

    def node(state: IdeationConvState) -> dict:
        prompt = build_ideation_conv_canvas_update_prompt(
            state.get("idea_canvas"),
            state.get("selected_idea"),
            state.get("initial_idea"),
            state.get("discussion_planning_position"),
            state.get("discussion_development_review"),
            state.get("discussion_revised_proposal"),
            state["consensus"],
            state["unresolved_issues"],
            state["notice_and_criteria"],
        )
        try:
            raw, ok, attempts = _safe_call_structured_json(
                llm_call, prompt, _validate_canvas_response, "canvas_update"
            )
        except IdeationCancelled:
            raise
        except Exception:
            # 캔버스는 보조 표시 계층이다. 공급자 오류나 테스트용 LLM의 미지원 응답 때문에
            # 이미 완료된 전문가 회의까지 실패시키지 않는다. 취소 신호만은 반드시 전파한다.
            logger.warning("아이디어 캔버스 갱신 호출에 실패해 직전 값을 유지합니다", exc_info=True)
            return {"llm_calls_used": state.get("llm_calls_used", 0) + 1}
        used = state.get("llm_calls_used", 0) + attempts
        if not ok:
            return {"llm_calls_used": used}

        canvas: dict[str, Any] = {key: raw[key].strip() for key in _CANVAS_TEXT_FIELDS}
        canvas["feasibility"] = raw["feasibility"].strip()
        canvas["risks"] = _as_string_list(raw.get("risks"))[:_MAX_CANVAS_RISKS]
        return {"idea_canvas": canvas, "llm_calls_used": used}

    return node


def make_conv_synthesis_node(llm_call: LLMCall) -> Callable[[IdeationConvState], dict]:
    """사용자가 확정 버튼을 눌렀을 때만 실행되는 최종 종합 노드(요청 9~10번 — 오케스트레이션
    레벨에서 phase="finalizing"으로만 진입 가능하게 막아 두었으므로, 이 노드 자체가 또
    안전장치를 하나 더 두는 것은 아니다 — ideation_conv_run.py::finalize_ideation_conversation()
    참고)."""

    def node(state: IdeationConvState) -> dict:
        discovery_history = None
        if state.get("ideation_mode") == "discovery":
            # 요청 8번 — discovery 세션이면 최초 생성 후보/선택된 후보/선택 이유를 최종
            # 결과에 포함한다. state["ideation_mode"]를 여기서 다시 판단하지 않고(이미
            # initial_conv_state가 결정한 값을) 그대로 읽기만 한다.
            discovery_history = {
                "original_candidates": state.get("original_idea_candidates", []),
                "selected_idea": state.get("selected_idea"),
                "selection_reason": state.get("selection_reason"),
            }
        prompt = build_ideation_conv_synthesis_prompt(
            state["notice_and_criteria"],
            state["user_idea"],
            state["messages"],
            state["consensus"],
            state["unresolved_issues"],
            discovery_history=discovery_history,
        )
        raw, ok = _safe_call_json(llm_call, prompt)
        used = state.get("llm_calls_used", 0) + 1
        if not ok:
            return {"phase": "failed", "failed_node": "conv_synthesis", "llm_calls_used": used}
        return {"idea_proposal": raw, "phase": "finalized", "llm_calls_used": used}

    return node
