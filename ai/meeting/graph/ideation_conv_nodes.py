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
    IdeationConvState,
    remaining_topics_for,
)
from .ideation_nodes import EvidenceLookup, _safe_call_json
from .llm import LLMCall, parse_json_response

logger = logging.getLogger(__name__)

_VALID_DISCUSSION_STANCES = {"동의", "조건부_동의", "반박", "보완", "대안_제시"}
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

# 역할별 발언 헤더(요청 5번) — JSON 스키마 키는 역할과 무관하게 동일하고, 화면에 보이는
# 라벨만 역할에 따라 다르게 조립한다. _compose_discussion_content()와
# ideation_conversation_streaming.py(스트리밍 헤더 해석)가 공유한다.
PLANNING_DISCUSSION_HEADERS: dict[str, str] = {
    "judgment": "[기획 관점]",
    "reason": "[근거]",
    "suggestion": "[제안]",
    "responding_to": "[상대 의견 검토]",
    "agreement": "[동의]",
    "concern": "[우려·제약]",
    "revision": "[수정 내용]",
    "interim_conclusion": "[임시 결론]",
}
DEV_DISCUSSION_HEADERS: dict[str, str] = {
    "judgment": "[기술 검토]",
    "reason": "[근거]",
    "suggestion": "[구현 대안]",
    "responding_to": "[상대 의견 검토]",
    "agreement": "[동의하는 부분]",
    "concern": "[우려/제약]",
    "revision": "[수정 내용]",
    "interim_conclusion": "[임시 결론]",
}


def discussion_headers_for(persona_id: str) -> dict[str, str]:
    return DEV_DISCUSSION_HEADERS if persona_id == "dev_expert" else PLANNING_DISCUSSION_HEADERS

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
            continue
        problem = validate(raw)
        if problem is None:
            return raw, True, attempt
        last_reason = problem
    logger.warning("[%s] 구조화 응답 검증 실패 reason=%s", node_name, last_reason)
    return None, False, 2


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
        if require_combine_structure:
            if _blank(raw.get("user_selection_summary")):
                return "missing_or_empty_field:user_selection_summary"
            if _blank(raw.get("proposal")):
                return "missing_or_empty_field:proposal"
        return None

    return _validate


def _validate_discussion_response(raw: dict, discussion_stage: str = "initial_position") -> str | None:
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
    if discussion_stage in ("review", "revision"):
        if _blank(raw.get("responding_to")):
            return "missing_or_empty_field:responding_to"
        agreement = (raw.get("agreement") or "").strip()
        concern = (raw.get("concern") or "").strip()
        if not agreement and not concern:
            return "missing_or_empty_field:agreement_or_concern"
    return None


def _validate_facilitator_response(raw: dict) -> str | None:
    if _blank(raw.get("facilitator_summary")):
        return "missing_or_empty_field:facilitator_summary"
    if bool(raw.get("needs_user_decision")) and _blank(raw.get("user_question")):
        return "missing_or_empty_field:user_question"
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
) -> ConvMessage:
    """structured는 선택 필드다(요청 9번 — 프런트 "상세 보기" 토글용, 기존 content 문자열은
    그대로 유지한 채 순수 추가). opinion/agreement/disagreement 메시지만 값을 채우고
    (make_conv_discussion_node 참고), 질문/답변/설명/요약 메시지는 None으로 둔다 — 기존
    content 렌더링만으로도 완전한 정보이기 때문이다."""
    speaker_name, role = _speaker_fields(persona_id)
    return ConvMessage(
        message_id=_new_message_id(),
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


def _compose_question_content(
    judgment: str, question: str, user_selection_summary: str | None = None, proposal: str | None = None
) -> str:
    """요청 2번 출력 형식([현재 판단]/[핵심 질문])을 화면에 그대로 보이는 content 문자열로
    조립한다 — 프론트는 message.content를 그대로 렌더링하므로, 구조는 여기서 문자열로
    고정하고 프론트는 건드리지 않는다.

    용준/Claude(2026-07-21, 후보 결합 컨텍스트 보존): user_selection_summary/proposal이
    채워져 있으면(=후보 결합 직후 첫 전문가 메시지, 요청 6번) [사용자 선택 반영]/[제안]
    섹션을 추가한 4단계 구조로 조립한다. 둘 다 없으면(일반 질문 턴) 기존 2단계 구조를
    그대로 유지한다 — refinement/기존 discovery select·recommend 흐름은 전혀 바뀌지
    않는다."""
    if user_selection_summary and proposal:
        return (
            f"[사용자 선택 반영]\n{user_selection_summary}\n\n"
            f"[현재 판단]\n{judgment}\n\n"
            f"[제안]\n{proposal}\n\n"
            f"[핵심 질문]\n{question}"
        )
    return f"[현재 판단]\n{judgment}\n\n[핵심 질문]\n{question}"


def _compose_discussion_content(
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
    """요청 5번 출력 구조(역할별 헤더 — 기획: [기획 관점]/[근거]/[제안]/..., 개발: [기술
    검토]/[근거]/[구현 대안]/...)를 content 문자열로 조립한다. JSON 키(judgment/suggestion 등)
    자체는 역할과 무관하게 동일하고, discussion_headers_for(persona_id)가 화면 라벨만
    바꾼다 — [핵심 질문] 섹션은 애초에 이 노드의 출력이 아니다(질문 노드 전용이라 여기서
    만들 필요가 없다).

    용준/Claude(2026-07-21, 요청: 위원 간 실제 회의로 개편): responding_to/agreement/concern/
    revision은 discussion_stage가 "review"(상대 의견 검토) 또는 "revision"(검토 반영 수정)일
    때만 값이 있다 — 값이 있는 섹션만 순서대로 끼워 넣는다. interim_conclusion(임시 결론,
    요청 4번)은 모든 단계에서 항상 채워진다. 이 함수의 섹션 이름·순서는
    DISCUSSION_STREAM_FIELDS와 정확히 일치해야 한다(다르면 스트리밍 중 보이는 텍스트와
    완료 후 canonical 메시지가 어긋난다)."""
    headers = discussion_headers_for(persona_id)
    parts = [f"{headers['judgment']}\n{judgment}", f"{headers['reason']}\n{reason}", f"{headers['suggestion']}\n{suggestion}"]
    if responding_to:
        parts.append(f"{headers['responding_to']}\n{responding_to}")
    if agreement:
        parts.append(f"{headers['agreement']}\n{agreement}")
    if concern:
        parts.append(f"{headers['concern']}\n{concern}")
    if revision:
        parts.append(f"{headers['revision']}\n{revision}")
    parts.append(f"{headers['interim_conclusion']}\n{interim_conclusion}")
    parts.append(f"[확정 사항]\n{_bullets(confirmed)}")
    parts.append(f"[미확정 사항]\n{_bullets(unconfirmed)}")
    return "\n\n".join(parts)


# 용준/Claude(2026-07-21, 요청: 실시간 스트리밍) — 사용자에게 실제로 보여줄 텍스트를 담는
# JSON 필드 이름을, 화면에 붙는 섹션 헤더와 함께 (field_name, header) 순서쌍으로 노출한다.
# backend/app/api/routes/ideation_conversation_preview.py의 스트리밍 llm_call이 이 목록
# 그대로 써서 OpenAI 델타 안에서 어떤 필드의 텍스트를 어떤 헤더 아래 흘려보낼지 정한다.
# 위 _compose_question_content/_compose_discussion_content/make_expert_delegation_message가
# 최종적으로 조립하는 순서·문구와 반드시 동일해야 한다(다르면 스트리밍 중 보이는 텍스트와
# 완료 후 canonical 메시지가 어긋난다) — 이 상수들이 그 두 곳의 유일한 출처다. 헤더가 None인
# 항목(EXPERT_DELEGATION의 "proposal")은 페르소나 표시 이름에 따라 달라지므로 호출부가
# 동적으로 만든다.
QUESTION_STREAM_FIELDS: tuple[tuple[str, str], ...] = (
    ("user_selection_summary", "[사용자 선택 반영]"),
    ("judgment", "[현재 판단]"),
    ("proposal", "[제안]"),
    ("question", "[핵심 질문]"),
)
DISCUSSION_STREAM_FIELDS: tuple[tuple[str, str | None], ...] = (
    ("judgment", None),
    ("reason", None),
    ("suggestion", None),
    # 용준/Claude(2026-07-21, 요청: 위원 간 실제 회의로 개편) — discussion_stage가
    # "review"/"revision"일 때만 LLM이 이 필드들을 채운다(null이면 JSONFieldStreamer가
    # 조용히 건너뛴다 — json_stream.py의 null 처리 참고). initial_position 단계는 이
    # 필드들이 항상 null이라 스트리밍에 아무 영향이 없다.
    ("responding_to", None),
    ("agreement", None),
    ("concern", None),
    ("revision", None),
    # 용준/Claude(2026-07-21, 요청: 전문가 라운드테이블 전환) — 매 발언 필수인 임시 결론
    # (요청 4번). 항상 값이 있으므로 매번 스트리밍된다.
    ("interim_conclusion", None),
)
# 용준/Claude(2026-07-21, 요청: 전문가 라운드테이블 전환) — 위 8개 필드는 역할별로 다른
# 헤더를 쓴다(discussion_headers_for) — 정적 헤더를 전부 None으로 비워 두었으므로
# ideation_conversation_streaming.py가 프롬프트에서 판별한 persona_id로 header_resolver를
# 만들어 붙인다.
FACILITATOR_SUMMARY_STREAM_FIELDS: tuple[tuple[str, str | None], ...] = (
    ("facilitator_summary", None),
    # needs_user_decision=false이면 LLM이 user_question을 null로 두므로 JSONFieldStreamer가
    # 조용히 건너뛴다. [합의 사항]/[남은 쟁점] 섹션은(confirmed/unconfirmed와 같은 기존
    # 관례처럼) 배열 값이라 실시간 스트리밍 대상이 아니고, canonical 메시지가 완성될 때
    # 한 번에 붙는다 — make_discussion_facilitator_node()의 content 조립과 정확히 같은
    # 헤더("[사용자 의견이 필요한 사항]", 요청 5번)를 스트리밍 중에도 재현한다.
    ("user_question", "[사용자 의견이 필요한 사항]"),
)
EXPERT_DELEGATION_STREAM_FIELDS: tuple[tuple[str, str | None], ...] = (
    ("proposal", None),
    ("reason", "[제안 이유]"),
    ("assumption", "[임시 가정]"),
    # 용준/Claude(2026-07-21, 요청: expert_delegation도 위원 간 상호 검토로 확장) —
    # stage="revision"일 때만 채워진다(initial이면 null이라 JSONFieldStreamer가 건너뛴다).
    ("responding_to", "[상대 검토 반영]"),
    ("revision", "[수정 내용]"),
)
# make_expert_delegation_message가 assumption 뒤에 항상 고정으로 덧붙이는 문구 — 스트리밍
# 종료 직후 화면에도 동일하게 붙여야 canonical 메시지와 스트리밍 미리보기가 일치한다.
EXPERT_DELEGATION_TRAILER = "\n\n사용자가 나중에 다른 방향을 제시하면 이 가정은 언제든 수정할 수 있습니다."

# 용준/Claude(2026-07-21, 요청: expert_delegation도 위원 간 상호 검토로 확장) — 담당 전문가의
# 임시 제안을 반대 역할 전문가가 검토하는 턴의 스트리밍 필드.
DELEGATION_REVIEW_STREAM_FIELDS: tuple[tuple[str, str | None], ...] = (
    ("judgment", "[검토]"),
    ("reason", "[근거]"),
    ("responding_to", "[제안 검토]"),
    ("agreement", "[동의]"),
    ("concern", "[우려/제약]"),
    ("recommendation", "[검토 결론]"),
)
# 위임 흐름 전용 진행자 최종 권고안 — 사용자에게 되물을 필드가 스키마에 아예 없으므로
# (요청: "다시 사용자에게 같은 질문을 넘기면 안 됩니다") facilitator_summary와 달리 두 번째
# 스트림 필드가 없다.
DELEGATION_FACILITATOR_STREAM_FIELDS: tuple[tuple[str, str | None], ...] = (("final_recommendation", None),)


def _topic_query(state: IdeationConvState) -> str:
    if state["round"] > 1 and state.get("unresolved_issues"):
        return " ".join(state["unresolved_issues"])
    idea = state["user_idea"]
    if isinstance(idea, dict):
        return " ".join(str(v) for v in idea.values() if v)
    return str(idea)


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
    질문/의견 메시지와 통일한다."""
    content = f"[재질문]\n{reason}\n\n[핵심 질문]\n{follow_up_question}"
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
    규칙] 참고) — 이 함수는 그 값을 메시지 스키마로 감싸기만 한다."""
    content = f"[설명]\n{clarification_response}"
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


def _compose_expert_delegation_content(
    persona_id: str, proposal: str, reason: str, assumption: str, responding_to: str | None, revision: str | None
) -> str:
    """전문가 위임 제안 메시지를 [{표시 이름} 제안]/[제안 이유]/[임시 가정] 구조로 조립한다
    (요청 사항의 예시 구조 그대로). 이 제안은 사실 확정이 아니라 임시 가정임을 항상
    명시한다(요청 10번) — "사용자가 나중에 다른 방향을 제시하면 수정할 수 있다"는 문구는
    LLM이 빠뜨려도 항상 보장하도록 여기서 고정으로 덧붙인다. responding_to/revision은
    stage="revision"일 때만 값이 있다 — 스트리밍 시 EXPERT_DELEGATION_TRAILER가 assumption
    섹션 바로 뒤(=이 두 섹션보다 앞)에 삽입되므로, 이 함수도 반드시 같은 순서를 지킨다."""
    display_name, _role = _speaker_fields(persona_id)
    content = (
        f"[{display_name} 제안]\n{proposal}\n\n"
        f"[제안 이유]\n{reason}\n\n"
        f"[임시 가정]\n{assumption}\n\n"
        "사용자가 나중에 다른 방향을 제시하면 이 가정은 언제든 수정할 수 있습니다."
    )
    if responding_to:
        content += f"\n\n[상대 검토 반영]\n{responding_to}"
    if revision:
        content += f"\n\n[수정 내용]\n{revision}"
    return content


def make_expert_delegation_message(
    *,
    persona_id: str,
    round_number: int,
    proposal: str,
    reason: str,
    assumption: str,
    referenced_message_ids: Any,
    evidence: Any,
    known_message_ids: set[str],
    responding_to: str | None = None,
    revision: str | None = None,
) -> ConvMessage:
    content = _compose_expert_delegation_content(persona_id, proposal, reason, assumption, responding_to, revision)
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


def _compose_expert_delegation_review_content(
    judgment: str, reason: str, responding_to: str, agreement: str, concern: str, recommendation: str
) -> str:
    """generate_expert_delegation_review()의 raw 응답을 content 문자열로 조립한다. 섹션
    이름·순서는 DELEGATION_REVIEW_STREAM_FIELDS와 정확히 일치해야 한다."""
    parts = [f"[검토]\n{judgment}", f"[근거]\n{reason}", f"[제안 검토]\n{responding_to}"]
    if agreement:
        parts.append(f"[동의]\n{agreement}")
    if concern:
        parts.append(f"[우려/제약]\n{concern}")
    parts.append(f"[검토 결론]\n{recommendation}")
    return "\n\n".join(parts)


def make_expert_delegation_review_message(
    *,
    persona_id: str,
    round_number: int,
    raw: dict,
    known_message_ids: set[str],
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
    content = _compose_expert_delegation_review_content(judgment, reason, responding_to, agreement, concern, recommendation)
    return _build_message(
        persona_id=persona_id,
        round_number=round_number,
        message_type=message_type,
        content=content,
        referenced_message_ids=_referenced_ids(raw.get("referenced_message_ids"), known_message_ids),
        evidence=raw.get("evidence"),
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
    구조적으로 재질문이 불가능하다."""
    final_recommendation = raw.get("final_recommendation", "")
    considerations = _as_string_list(raw.get("considerations"))
    content = final_recommendation
    if considerations:
        content += f"\n\n[참고 사항]\n{_bullets(considerations)}"
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
) -> Callable[[IdeationConvState], dict]:
    """기획 전문가(planning_expert)/개발 전문가(dev_expert)의 "질문 턴" 노드를 만든다.
    질문 하나를 만들고 나면 반드시 awaiting_phase로 멈춘다 — 이 노드 자신은 절대
    다음 전문가로 이어가지 않는다(요청 4번: 기획 질문 직후, 개발 질문 직후 각각 정지)."""

    def node(state: IdeationConvState) -> dict:
        query = _topic_query(state)
        retrieved = evidence_lookup(persona_id, query) if evidence_lookup is not None else []
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

        judgment = raw.get("judgment", "")
        question = raw.get("question", "")
        question_topic = raw.get("question_topic")  # validate()가 이미 TOPIC_PRIORITY 소속을 보장한다.
        known_ids = {m["message_id"] for m in state["messages"]}
        message = _build_message(
            persona_id=persona_id,
            round_number=state["round"],
            message_type="question",
            content=_compose_question_content(judgment, question, raw.get("user_selection_summary"), raw.get("proposal")),
            referenced_message_ids=_referenced_ids(raw.get("referenced_message_ids"), known_ids),
            evidence=raw.get("evidence"),
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


# 용준/Claude(2026-07-21, 요청: 위원 간 실제 회의로 개편): dev_expert의 review 발언
# stance가 이 집합에 속할 때만 planning_expert_revision을 실행한다("동의"/"보완"은 원래
# 제안을 바꿀 만한 반론이 아니므로 수정 턴을 생략해 LLM 호출을 아낀다 — 요청 6번 "필요할
# 때만 수정 의견 1회"). 이 게이팅은 새 LLM 분류 호출 없이 review 응답에 이미 있는 stance
# 필드만으로 결정적으로 판단한다(비용 절감).
REVISION_TRIGGER_STANCES = {"반박", "조건부_동의", "대안_제시"}

_DISCUSSION_COUNTERPART = {"planning_expert": "dev_expert", "dev_expert": "planning_expert"}


def _most_recent_message_by(messages: list[ConvMessage], speaker_id: str, round_number: int | None = None) -> ConvMessage | None:
    for msg in reversed(messages):
        if msg.get("speaker_id") != speaker_id:
            continue
        if round_number is not None and msg.get("round") != round_number:
            continue
        return msg
    return None


def _responding_to_for(state: IdeationConvState, persona_id: str, discussion_stage: str) -> ConvMessage | None:
    """용준/Claude(2026-07-21, 요청: 전문가 라운드테이블 전환): 이번 발언이 실제로 무엇에
    반응하는지(responding_to_message_id/speaker_id)를 코드가 결정적으로 찾는다 — LLM이 존재
    하지 않는 id를 지어낼 위험을 피하기 위해 절대 LLM에게 맡기지 않는다(요청 4번: "화면에
    반드시 표시할 필요는 없지만 state에는 관계가 구조적으로 저장되어야 한다").

    "review"/"revision"이면 이번 라운드에서 상대 페르소나가 가장 최근에 남긴 메시지를
    찾는다. "initial_position"이면 상대 전문가가 아니라 이번 라운드를 연 진행자의 안건/
    직전 라운드 정리, 또는 그 사이에 사용자가 개입했다면 그 메시지 — 즉 messages 목록의
    마지막 메시지를 그대로 대상으로 삼는다(라운드 1의 첫 발언은 세션 시작 시 넣어 둔 진행자
    안건 제시 메시지를 가리키게 된다)."""
    messages = state["messages"]
    if discussion_stage in ("review", "revision"):
        counterpart = _DISCUSSION_COUNTERPART.get(persona_id)
        target = _most_recent_message_by(messages, counterpart, round_number=state["round"])
        return target or _most_recent_message_by(messages, counterpart)
    return messages[-1] if messages else None


def make_conv_discussion_node(
    persona_id: str,
    speaks_second: bool,
    llm_call: LLMCall,
    evidence_lookup: EvidenceLookup | None = None,
    discussion_stage: str = "initial_position",
) -> Callable[[IdeationConvState], dict]:
    """사용자가 두 질문에 모두 답한 뒤 실행되는 "보완 의견" 노드. speaks_second=True인
    쪽(개발 전문가, 두 번째로 말함)만 다음 행동(continue_round/await_user_decision)을
    판단한다 — 두 전문가 모두에게 판단을 맡기면 의견이 엇갈릴 수 있어, 라운드를 실제로
    마무리하는 쪽(마지막 발언자)에게만 그 권한을 준다. 어느 쪽도 "finalize"를 선택할 수
    없다(프롬프트 규칙 + 아래 안전장치 이중으로 막는다 — 요청 9~10번).

    discussion_stage(용준/Claude(2026-07-21, 요청: 위원 간 실제 회의로 개편)는 이 노드가
    회의 흐름의 어느 지점을 담당하는지 나타낸다 — "initial_position"(planning_expert의
    최초 의견, 기존 동작), "review"(dev_expert가 방금 나온 planning_expert 의견을 실제로
    검토, responding_to 필수), "revision"(planning_expert가 dev_expert의 구체적 우려를
    반영해 수정하거나 유지, 역시 responding_to 필수). 세 경우 모두 이 함수 하나를 그대로
    재사용한다 — 스키마·검증·메시지 조립 로직이 완전히 같고 프롬프트 안내문과 상태 저장
    위치만 다르기 때문이다."""

    def node(state: IdeationConvState) -> dict:
        query = _topic_query(state)
        retrieved = evidence_lookup(persona_id, query) if evidence_lookup is not None else []
        context = conversation_context_for(state)
        prompt = build_ideation_conv_discussion_prompt(
            persona_id,
            state["notice_and_criteria"],
            state["user_idea"],
            retrieved,
            context,
            speaks_second,
            discussion_stage=discussion_stage,
        )
        validate = lambda raw, _stage=discussion_stage: _validate_discussion_response(raw, _stage)  # noqa: E731
        raw, ok, attempts = _safe_call_structured_json(llm_call, prompt, validate, f"discussion__{persona_id}")
        used = state.get("llm_calls_used", 0) + attempts
        if not ok:
            return {"phase": "failed", "failed_node": f"discussion__{persona_id}", "llm_calls_used": used}

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

        # 요청 4번 — 상호참조는 코드가 결정한다(LLM이 아니라).
        responding_to_target = _responding_to_for(state, persona_id, discussion_stage)
        responding_to_message_id = responding_to_target["message_id"] if responding_to_target else None
        responding_to_speaker_id = responding_to_target["speaker_id"] if responding_to_target else None
        referenced_ids_raw = list(raw.get("referenced_message_ids") or [])
        if responding_to_message_id and responding_to_message_id not in referenced_ids_raw:
            referenced_ids_raw.append(responding_to_message_id)

        content = _compose_discussion_content(
            persona_id,
            judgment,
            reason,
            suggestion,
            confirmed_items,
            unconfirmed_items,
            interim_conclusion,
            responding_to,
            agreement,
            concern,
            revision_text,
        )
        message = _build_message(
            persona_id=persona_id,
            round_number=state["round"],
            message_type=message_type,
            content=content,
            referenced_message_ids=_referenced_ids(referenced_ids_raw, known_ids),
            evidence=raw.get("evidence"),
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
                # 요청 4번 — 상대 발언 참조를 구조적으로 저장한다(화면 노출은 선택).
                "responding_to_message_id": responding_to_message_id,
                "responding_to_speaker_id": responding_to_speaker_id,
            },
        )

        new_consensus = list(state["consensus"])
        for item in _as_string_list(raw.get("confirmed")):
            if item not in new_consensus:
                new_consensus.append(item)

        unconfirmed = _as_string_list(raw.get("unconfirmed"))
        update: dict[str, Any] = {
            "messages": [message],
            "consensus": new_consensus,
            # "unconfirmed" 키 자체가 없으면(구버전 응답 등) 기존 unresolved_issues를 그대로
            # 둔다 — 키가 있는데 배열이 아니면(타입 오류) 안전하게 빈 배열로 정규화한다.
            "unresolved_issues": unconfirmed if "unconfirmed" in raw else state["unresolved_issues"],
            "llm_calls_used": used,
        }

        # 용준/Claude(2026-07-21, 요청: 위원 간 실제 회의로 개편) — discussion_facilitator가
        # 이번 라운드 세 발언(최초/검토/수정)을 한 번에 정리할 수 있도록 raw 응답을 단계별
        # 임시 필드에 저장한다(state.py::discussion_planning_position 등 참고, 다음 라운드가
        # 시작되면 새 값으로 덮어써진다).
        if discussion_stage == "initial_position":
            update["discussion_planning_position"] = raw
        elif discussion_stage == "review":
            update["discussion_development_review"] = raw
            update["discussion_review_stance"] = stance
        elif discussion_stage == "revision":
            update["discussion_revised_proposal"] = raw

        if not speaks_second:
            # 이번 라운드의 첫 의견(또는 revision 발언)  — 아직 라운드를 끝낼 권한이 없다.
            # phase는 그대로 두어 그래프가 다음 노드를 실행하게 한다(ideation_conv_build.py의
            # 고정 순차/조건부 엣지가 결정한다).
            return update

        # speaks_second=True(review 단계): 이번 라운드를 계속할지(다음 라운드 기획 질문으로)
        # 사용자 결정을 기다릴지 결정한다. round_number가 max_rounds에 도달하면 LLM 판단과
        # 무관하게 강제로 await_user_decision으로 보낸다(무한 라운드 방지, 배치형
        # facilitator의 강제 finalize와 같은 원칙) — 그리고 이 노드는 "finalize"라는
        # next_action 값 자체를 아예 모른다(허용 집합에 없음), 그래서 LLM이 무엇을
        # 반환하든 최종 확정으로 이어질 수 없다(요청 9~10번의 이중 안전장치). 이 결정
        # (phase)은 discussion_facilitator가 절대 바꾸지 않는다 — 정리 메시지만 덧붙인다.
        next_action = raw.get("next_action")
        if state["round"] >= state["max_rounds"] or next_action != "continue_round":
            update["phase"] = "awaiting_user_decision"
            update["pending_question"] = None
            update["discussion_next_action"] = "await_user_decision"
        else:
            update["phase"] = "planning_question"
            update["round"] = state["round"] + 1
            update["pending_question"] = None
            update["discussion_next_action"] = "continue_round"

        return update

    return node


def make_discussion_facilitator_node(llm_call: LLMCall) -> Callable[[IdeationConvState], dict]:
    """용준/Claude(2026-07-21, 요청: 위원 간 실제 회의로 개편): 기획/개발 두 전문가의 이번
    라운드 보완 의견(및 있었다면 수정 의견)이 끝난 직후 항상 실행되어, 실제 발언 내용을
    바탕으로 진행자가 합의/이견을 정리하는 메시지 하나를 만든다. dev_expert_discussion이
    이미 정한 phase(next_action)는 절대 건드리지 않는다 — 기존에 검증된 라운드 진행/
    max_rounds 강제 로직을 그대로 재사용하기 위함이다(요청: 최소 변경)."""

    def node(state: IdeationConvState) -> dict:
        decided_next_action = state.get("discussion_next_action") or "await_user_decision"
        prompt = build_ideation_conv_discussion_facilitator_prompt(
            state["notice_and_criteria"],
            state.get("discussion_planning_position"),
            state.get("discussion_development_review"),
            state.get("discussion_revised_proposal"),
            state["consensus"],
            state["unresolved_issues"],
            decided_next_action,
            state["round"],
            state["max_rounds"],
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
        # 용준/Claude(2026-07-21, 요청: 전문가 라운드테이블 전환) — 요청 5번 진행자 발언 구조
        # ([합의 사항]/[남은 쟁점]/[사용자 의견이 필요한 사항])를 그대로 반영한다. 사용자
        # 의견이 필요 없으면(needs_user_decision=False) "없음"을 명시해, 사용자가 답하지
        # 않아도 회의가 계속 진행된다는 것을 화면에서도 드러낸다.
        content = (
            f"{summary_text}\n\n"
            f"[합의 사항]\n{_bullets(agreements)}\n\n"
            f"[남은 쟁점]\n{_bullets(disagreements)}\n\n"
            f"[사용자 의견이 필요한 사항]\n{user_question if user_question else '없음 — 다음 라운드로 진행합니다.'}"
        )

        message = _build_message(
            persona_id="ideation_facilitator",
            round_number=state["round"],
            message_type="summary",
            content=content,
            referenced_message_ids=[],
            evidence=[],
            structured={
                "agreements": agreements,
                "disagreements": disagreements,
                "needs_user_decision": needs_user_decision,
                "user_question": user_question,
            },
        )

        new_consensus = list(state["consensus"])
        for item in agreements:
            if item not in new_consensus:
                new_consensus.append(item)

        def _snapshot(persona_id: str, raw_or_none: dict | None) -> str:
            if not raw_or_none:
                return ""
            return _compose_discussion_content(
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

        revised = state.get("discussion_revised_proposal")
        record = DiscussionRoundRecord(
            round=state["round"],
            planning_position=_snapshot("planning_expert", state.get("discussion_planning_position")),
            development_review=_snapshot("dev_expert", state.get("discussion_development_review")),
            revised_proposal=_snapshot("planning_expert", revised) if revised else None,
            facilitator_summary=summary_text,
            needs_user_decision=needs_user_decision,
        )

        update: dict[str, Any] = {
            "messages": [message],
            "consensus": new_consensus,
            "discussion_rounds": [record],
            "llm_calls_used": used,
        }
        # 용준/Claude(2026-07-21, 요청: 전문가 라운드테이블 전환) — 진행자가 실제로 사용자에게
        # 물었을 때만 pending_question을 채운다. reply_ideation_conversation이 이 값의 유무로
        # 다음 사용자 메시지를 "answer"(진행자 질문에 답함)와 "interjection"(자발적 개입)으로
        # 구분한다(요청 6번).
        if needs_user_decision and user_question:
            update["pending_question"] = user_question
            update["pending_question_topic"] = "facilitator_decision"
        else:
            update["pending_question"] = None
            update["pending_question_topic"] = None
        return update

    return node


# 가은/Claude(2026-07-22, 요청: 아이디어 기획 캔버스 자동 갱신 — 경이 협의 완료): 캔버스의
# 문자열 필드(키 이름은 selected_idea와 동일 — 프론트가 idea_canvas ?? selected_idea 폴백만으로
# 그릴 수 있게 한다)와 feasibility 허용값, risks 상한.
_CANVAS_TEXT_FIELDS = ("problem", "target_user", "core_value", "solution", "differentiation", "contest_fit")
_VALID_CANVAS_FEASIBILITY = {"high", "medium", "low", ""}
_MAX_CANVAS_RISKS = 4


def _validate_canvas_response(raw: dict) -> str | None:
    """캔버스 갱신 응답 검증. 다른 구조화 검증과 달리 "필수 문자열이 비어 있지 않을 것"을
    요구하지 않는다 — 아직 논의되지 않은 항목은 빈 문자열로 두는 것이 규칙(프롬프트 2번)
    이기 때문이다. 키 존재/타입/feasibility 허용값만 본다."""
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
    """가은/Claude(2026-07-22, 요청: 아이디어 기획 캔버스 자동 갱신 — 경이 협의 완료): 라운드테이블
    한 라운드(discussion_facilitator까지)가 끝난 직후 실행되어, 이번 라운드 발언으로 프론트
    오른쪽 패널의 '아이디어 기획 캔버스'(state["idea_canvas"])를 갱신한다.

    이 노드만의 두 가지 예외적 성질:
      - 메시지를 만들지 않는다 — 화면에 보이는 발언이 아니라 구조화 값만 갱신한다(스트리밍
        레이어에서는 _PHASE_ONLY_LABELS의 진행 문구만 나간다).
      - 비치명적이다 — 검증 실패 시 phase="failed"로 바꾸지 않고 직전 캔버스를 그대로 둔다.
        캔버스는 부가 정보라서, 이것 때문에 이미 성공한 라운드 전체를 실패로 만들면 안 된다
        (회의 진행 로직과의 유일한 접점은 llm_calls_used 누적뿐이다). phase도 절대 바꾸지
        않는다 — 다음 라우팅(ideation_conv_build.py::_route_after_facilitator)은
        dev_expert_discussion이 이미 정한 phase를 그대로 읽어야 한다."""

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
        raw, ok, attempts = _safe_call_structured_json(llm_call, prompt, _validate_canvas_response, "canvas_update")
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
