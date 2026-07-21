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
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from prompts import (
    build_ideation_conv_discussion_prompt,
    build_ideation_conv_question_prompt,
    build_ideation_conv_sufficiency_prompt,
    build_ideation_conv_synthesis_prompt,
    get_persona_card,
)

from .ideation_conv_state import TOPIC_PRIORITY, ConvMessage, IdeationConvState, remaining_topics_for
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
_VALID_ANSWER_TYPES = {"answer", "clarification_request", "insufficient_answer"}

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


def _validate_discussion_response(raw: dict) -> str | None:
    if _blank(raw.get("judgment")) or _blank(raw.get("reason")):
        return "missing_or_empty_field:judgment_or_reason"
    if len(raw.get("judgment", "")) > _MAX_JUDGMENT_CHARS:
        return "judgment_too_long"
    if len(raw.get("reason", "")) > _MAX_REASON_CHARS:
        return "reason_too_long"
    if len(raw.get("suggestion") or "") > _MAX_SUGGESTION_CHARS:
        return "suggestion_too_long"
    confirmed = raw.get("confirmed")
    if isinstance(confirmed, list) and len(confirmed) > _MAX_CONFIRMED_ITEMS:
        return "confirmed_too_many_items"
    unconfirmed = raw.get("unconfirmed")
    if isinstance(unconfirmed, list) and len(unconfirmed) > _MAX_UNCONFIRMED_ITEMS:
        return "unconfirmed_too_many_items"
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


def _compose_discussion_content(judgment: str, reason: str, suggestion: str, confirmed: Any, unconfirmed: Any) -> str:
    """요청 4번 출력 구조([판단]/[근거]/[제안]/[확정 사항]/[미확정 사항])를 content 문자열로
    조립한다."""
    return (
        f"[판단]\n{judgment}\n\n"
        f"[근거]\n{reason}\n\n"
        f"[제안]\n{suggestion}\n\n"
        f"[확정 사항]\n{_bullets(confirmed)}\n\n"
        f"[미확정 사항]\n{_bullets(unconfirmed)}"
    )


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


def make_conv_discussion_node(
    persona_id: str,
    speaks_second: bool,
    llm_call: LLMCall,
    evidence_lookup: EvidenceLookup | None = None,
) -> Callable[[IdeationConvState], dict]:
    """사용자가 두 질문에 모두 답한 뒤 실행되는 "보완 의견" 노드. speaks_second=True인
    쪽(개발 전문가, 두 번째로 말함)만 다음 행동(continue_round/await_user_decision)을
    판단한다 — 두 전문가 모두에게 판단을 맡기면 의견이 엇갈릴 수 있어, 라운드를 실제로
    마무리하는 쪽(마지막 발언자)에게만 그 권한을 준다. 어느 쪽도 "finalize"를 선택할 수
    없다(프롬프트 규칙 + 아래 안전장치 이중으로 막는다 — 요청 9~10번)."""

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
        )
        raw, ok, attempts = _safe_call_structured_json(
            llm_call, prompt, _validate_discussion_response, f"discussion__{persona_id}"
        )
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
        confirmed_items = _as_string_list(raw.get("confirmed"))
        unconfirmed_items = _as_string_list(raw.get("unconfirmed"))
        content = _compose_discussion_content(judgment, reason, suggestion, confirmed_items, unconfirmed_items)
        message = _build_message(
            persona_id=persona_id,
            round_number=state["round"],
            message_type=message_type,
            content=content,
            referenced_message_ids=_referenced_ids(raw.get("referenced_message_ids"), known_ids),
            evidence=raw.get("evidence"),
            # 용준/Claude(2026-07-21, 프런트 상세보기): content(위)는 하위 호환을 위해 그대로
            # 유지하고, 필드별 구조를 선택 정보로 추가한다 — 프런트가 판단/제안만 기본 노출하고
            # 근거/확정/미확정을 "상세 보기"로 접을 수 있게 한다(요청 9번). content를 대체하는
            # 것이 아니라 순수 추가다.
            structured={
                "judgment": judgment,
                "reason": reason,
                "suggestion": suggestion,
                "confirmed": confirmed_items,
                "unconfirmed": unconfirmed_items,
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

        if not speaks_second:
            # 이번 라운드의 첫 의견 — 아직 라운드를 끝낼 권한이 없다. phase는 그대로 두어
            # 그래프가 이어서 두 번째 전문가 노드를 실행하게 한다(ideation_conv_build.py의
            # 고정 순차 엣지, 조건부 라우팅이 아니다).
            return update

        # speaks_second=True: 이번 라운드를 계속할지(다음 라운드 기획 질문으로) 사용자
        # 결정을 기다릴지 결정한다. round_number가 max_rounds에 도달하면 LLM 판단과
        # 무관하게 강제로 await_user_decision으로 보낸다(무한 라운드 방지, 배치형
        # facilitator의 강제 finalize와 같은 원칙) — 그리고 이 노드는 "finalize"라는
        # next_action 값 자체를 아예 모른다(허용 집합에 없음), 그래서 LLM이 무엇을
        # 반환하든 최종 확정으로 이어질 수 없다(요청 9~10번의 이중 안전장치).
        next_action = raw.get("next_action")
        if state["round"] >= state["max_rounds"] or next_action != "continue_round":
            update["phase"] = "awaiting_user_decision"
            update["pending_question"] = None
        else:
            update["phase"] = "planning_question"
            update["round"] = state["round"] + 1
            update["pending_question"] = None

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
