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
from .ideation_trace import sanitize_preview, trace_event
from .llm import LLMCall, parse_json_response

logger = logging.getLogger(__name__)

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
) -> ConvMessage:
    """structured는 선택 필드다(요청 9번 — 프런트 "상세 보기" 토글용, 기존 content 문자열은
    그대로 유지한 채 순수 추가). opinion/agreement/disagreement 메시지만 값을 채우고
    (make_conv_discussion_node 참고), 질문/답변/설명/요약 메시지는 None으로 둔다 — 기존
    content 렌더링만으로도 완전한 정보이기 때문이다."""
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
            content=_compose_question_content(raw.get("spoken_text", "")),
            referenced_message_ids=_referenced_ids(raw.get("referenced_message_ids"), known_ids),
            # 용준/Claude(2026-07-22, RAG 근거 유실 수정): 예전에는 raw.get("evidence")로 LLM이
            # JSON 응답에 자발적으로 되돌려준 evidence만 저장했다 — 이 필드는 검증되지 않는
            # 선택 필드라 대부분의 응답이 비워 보냈고, 그 결과 retrieved(위에서 RAG 검색으로
            # 실제로 찾아 프롬프트에 주입한 근거)가 있어도 메시지·로그(IDEATION_TURN_END의
            # evidence_count)에는 항상 0으로 남았다. 프롬프트에 실제로 삽입한 근거(retrieved)를
            # 그대로 메시지 evidence로 저장해야 "삽입된 근거 수"가 사실과 일치한다.
            evidence=retrieved,
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


def make_conv_discussion_node(
    persona_id: str,
    llm_call: LLMCall,
    evidence_lookup: EvidenceLookup | None = None,
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
        query = _topic_query(state)
        evidence_started = time.perf_counter()
        retrieved = evidence_lookup(persona_id, query) if evidence_lookup is not None else []
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
        context = conversation_context_for(state)
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
            retrieved,
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

        # 상호참조는 LLM 호출 전에 코드가 결정하고 프롬프트/검증/저장에 같은 값을 쓴다.
        referenced_ids_raw = list(raw.get("referenced_message_ids") or [])
        if responding_to_message_id and responding_to_message_id not in referenced_ids_raw:
            referenced_ids_raw.append(responding_to_message_id)

        # 용준/Claude(2026-07-22, 요청: 동적 전문가 회의로 개편) — 다음 발언자/쟁점 판단
        # 필드. recommended_next_speaker는 여기서 정규화만 하고, 실제 라우팅 검증은
        # _route_next_expert_turn(그래프 라우터)이 한다(LLM 추천을 그대로 신뢰하지 않는다).
        active_issue_id = (raw.get("active_issue_id") or "").strip() or _fallback_issue_id(state)
        active_issue_title = (raw.get("active_issue_title") or "").strip() or active_issue_id
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
            # injected_evidence_count: 실제로 메시지·프롬프트에 담겨 나간 근거 수(위
            # IDEATION_TURN_START의 retrieved_evidence_count와 항상 같아야 한다 — evidence
            # 필드가 이제 LLM이 자체 보고한 값이 아니라 retrieved를 그대로 저장하기 때문).
            injected_evidence_count=len(message["evidence"]),
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
