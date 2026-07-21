# 작성자: 용준/Claude(2026-07-20)
# 목적: 대화형 아이디어 발전 회의(ideation-conversation) 실행 엔트리포인트. ideation_run.py
#       (배치형)와 같은 역할(그래프 조립 + State 초기화/갱신 + 실행)을 대화형 그래프에
#       대해 수행하지만, "한 번의 함수 호출 = HTTP 요청 한 번"이 되도록 훨씬 잘게 나뉜다.
#       start_ideation_conversation()은 세션 시작(기획 전문가 첫 질문 하나), reply_to_*는
#       사용자 답변 반영 + 다음 정지 지점까지 실행, finalize_ideation_conversation()은
#       오직 사용자가 확정 버튼을 눌렀을 때만 호출된다(요청 9~10항).
# import: 표준 라이브러리 typing/uuid/datetime, 같은 패키지의 ideation_conv_build/state/llm.

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from .ideation_conv_build import assemble_ideation_conversation_graph
from .ideation_conv_nodes import (
    PHASE_TO_PENDING_PERSONA,
    conversation_context_for,
    judge_answer_sufficiency,
    make_clarification_message,
    make_follow_up_message,
)
from .ideation_conv_state import (
    ConvMessage,
    IdeationConvState,
    apply_user_answer,
    initial_conv_state,
    is_graph_entry_phase,
    request_finalize,
)
from .llm import LLMCall

IdeationConvProgressCallback = Callable[[dict], None]

# API가 사용자 입력을 받아도 되는(=그래프를 다시 부르지 않고 멈춰 있어야 하는) phase.
# 용준/Claude(2026-07-21): discovery(아이디어 발굴) 모드의 후보 선택 대기 phase를 추가한다
# — PHASE_TO_PENDING_PERSONA에는 없는 phase이므로 answer_sufficiency 게이트(아래 참고)는
# 자동으로 건너뛰고 apply_user_answer -> candidate_selection 노드로 그대로 이어진다(요청:
# 후보 선택 전에는 refinement 질문이 실행되지 않고, 선택은 재질문 판정 대상도 아니다).
REPLYABLE_PHASES = {
    "awaiting_planning_answer",
    "awaiting_developer_answer",
    "awaiting_user_decision",
    "awaiting_candidate_selection",
}

# 같은 쟁점(pending_question)으로 재질문할 수 있는 최대 횟수. 요청 3번(재질문 조건)의 예시
# "재질문이 2회 이상 반복되면... 합리적인 가정을 제시하고 다음 단계로 진행한다"를 그대로
# 코드 상수로 옮긴 값 — LLM 판정과 무관하게 이 값에 도달하면 강제로 다음 단계로 넘어간다
# (요청 5번 "라운드가 끝없이 반복되지 않도록" 무한 재질문 방지, max_rounds와는 별개의 축).
_MAX_ANSWER_RETRY = 2


def _new_user_message(content: str, round_number: int) -> ConvMessage:
    """사용자 발언 메시지를 조립한다. speaker_id="user"는 persona_cards.json에 없는
    값이라 ideation_conv_nodes.py의 페르소나 기반 헬퍼를 재사용할 수 없어 여기서 직접
    만든다 — message_id/created_at은 다른 메시지와 동일하게 항상 서버가 만든다."""
    return ConvMessage(
        message_id=f"MSG-{uuid.uuid4().hex[:10]}",
        speaker_id="user",
        speaker_name="사용자",
        role="사용자",
        round=round_number,
        message_type="answer",
        content=content,
        referenced_message_ids=[],
        evidence=[],
        created_at=datetime.now(timezone.utc).isoformat(),
        structured=None,
    )


def _progress(snapshot: IdeationConvState) -> dict:
    return {
        "phase": snapshot.get("phase"),
        "round": snapshot.get("round"),
        "messages_done": len(snapshot.get("messages") or []),
        "llm_calls_used": snapshot.get("llm_calls_used"),
    }


def _drive_graph(
    graph: Any,
    state: IdeationConvState,
    on_progress: IdeationConvProgressCallback | None = None,
) -> IdeationConvState:
    final_state: IdeationConvState = state
    for snapshot in graph.stream(state, stream_mode="values"):
        final_state = snapshot
        if on_progress is not None:
            on_progress(_progress(snapshot))
    return final_state


def start_ideation_conversation(
    *,
    session_id: str,
    notice_and_criteria: dict[str, Any],
    user_idea: dict[str, Any],
    llm_call: LLMCall,
    max_rounds: int = 3,
    evidence_lookup=None,
    on_progress: IdeationConvProgressCallback | None = None,
) -> IdeationConvState:
    """세션을 시작해 기획 전문가의 첫 질문 하나만 만들고 멈춘다(요청 목표 흐름 1~3번)."""
    graph = assemble_ideation_conversation_graph(llm_call, evidence_lookup=evidence_lookup)
    state = initial_conv_state(session_id, notice_and_criteria, user_idea, max_rounds=max_rounds)
    return _drive_graph(graph, state, on_progress)


def _apply_answer_sufficiency_gate(
    *,
    previous_state: IdeationConvState,
    persona_id: str,
    user_message: str,
    llm_call: LLMCall,
) -> tuple[IdeationConvState, IdeationConvState | None]:
    """사용자가 pending_question에 방금 남긴 메시지가 답변인지, 설명 요청인지, 불충분한
    답변인지 판정하고 그에 맞게 처리한다(요청 3번 + 용어 설명 요청을 재질문으로 오판하지
    않기).

    반환값은 (다음에 apply_user_answer에 넘길 previous_state, 그래프를 돌리지 않고 즉시
    끝낼 최종 state-또는-None) 튜플이다:
      - answer_type="answer"이거나 같은 쟁점 재질문이 이미 상한(_MAX_ANSWER_RETRY)에
        도달했으면 두 번째 값은 None이다 — 호출부가 이어서 apply_user_answer + 그래프 실행을
        정상 진행한다(요청 5번: 상한 도달 시 판정 결과와 무관하게 강제로 다음 단계로 진행,
        이때 판정이 여전히 insufficient_answer였다면 그 사실을 unresolved_issues에 "합리적
        가정"으로 남겨 둔다).
      - answer_type="clarification_request"이면, 사용자의 요청 메시지와 설명+선택지+재질문을
        담은 명확화 응답을 메시지로 추가한 최종 state를 두 번째 값으로 반환한다. pending_question/
        pending_expected_answer_type/answer_retry_count는 전혀 바뀌지 않는다 — 사용자가 아직
        원래 질문에 답하지 않았을 뿐, 불충분한 답을 한 것이 아니기 때문이다(요청: 재질문
        횟수를 늘리지 않는다).
      - answer_type="insufficient_answer"이고 아직 상한에 도달하지 않았으면, 사용자의 답변과
        좁혀진 재질문을 메시지로 추가한 최종 state를 두 번째 값으로 반환한다.
      호출부는 두 번째 값이 있으면 그래프를 전혀 실행하지 않고(정지 지점을 새로 만들지 않고)
      그 state를 그대로 돌려준다.

    resolved_topics(요청: 질문 주제 구조화)는 answer_type이 정확히 "answer"일 때만
    pending_question_topic을 추가한다 — clarification_request/insufficient_answer(재질문 진행
    중이든 상한 도달로 강제 진행하든)는 사용자가 그 주제에 실제로 명확히 답한 게 아니므로
    resolved로 표시하지 않는다(요청 3번 그대로).
    """
    pending_question = previous_state.get("pending_question") or ""
    expected_answer_type = previous_state.get("pending_expected_answer_type")
    retry_count = previous_state.get("answer_retry_count", 0)
    context = conversation_context_for(previous_state)
    judgment = judge_answer_sufficiency(
        llm_call,
        persona_id,
        pending_question,
        user_message,
        retry_count,
        context,
        expected_answer_type,
        user_idea=previous_state.get("user_idea"),
        idea_candidates=previous_state.get("idea_candidates"),
    )
    used = previous_state.get("llm_calls_used", 0) + 1
    answer_type = judgment["answer_type"]

    if answer_type == "clarification_request":
        answer_message = _new_user_message(user_message, previous_state["round"])
        clarification_message = make_clarification_message(
            persona_id=persona_id,
            round_number=previous_state["round"],
            clarification_response=judgment["clarification_response"] or judgment["reason"],
        )
        stop_state = IdeationConvState(
            **{
                **previous_state,
                "messages": previous_state["messages"] + [answer_message, clarification_message],
                "llm_calls_used": used,
                # pending_question/pending_expected_answer_type/answer_retry_count는 그대로
                # 유지한다 — 사용자는 여전히 같은 원래 질문에 답해야 한다.
            }
        )
        return previous_state, stop_state

    if answer_type == "answer" or retry_count >= _MAX_ANSWER_RETRY:
        updated_unresolved = previous_state["unresolved_issues"]
        resolved_topics = list(previous_state.get("resolved_topics") or [])
        if answer_type != "answer":
            # 상한 도달로 강제 진행 — 무엇이 불명확한 채로 남았는지 회의록에 남긴다. 이 주제는
            # 실제로 명확히 답해진 게 아니므로 resolved_topics에는 추가하지 않는다.
            note = f"{persona_id}: '{pending_question}'에 대한 답변이 불명확하여 다음 가정으로 진행합니다 — {judgment['reason']}"
            if note not in updated_unresolved:
                updated_unresolved = updated_unresolved + [note]
        else:
            pending_topic = previous_state.get("pending_question_topic")
            if pending_topic and pending_topic not in resolved_topics:
                resolved_topics = resolved_topics + [pending_topic]
        next_previous_state = IdeationConvState(
            **{
                **previous_state,
                "unresolved_issues": updated_unresolved,
                "resolved_topics": resolved_topics,
                "llm_calls_used": used,
            }
        )
        return next_previous_state, None

    follow_up_question = judgment["follow_up_question"] or pending_question
    answer_message = _new_user_message(user_message, previous_state["round"])
    follow_up_message = make_follow_up_message(
        persona_id=persona_id,
        round_number=previous_state["round"],
        reason=judgment["reason"],
        follow_up_question=follow_up_question,
    )
    stop_state = IdeationConvState(
        **{
            **previous_state,
            "messages": previous_state["messages"] + [answer_message, follow_up_message],
            "pending_question": follow_up_question,
            "answer_retry_count": retry_count + 1,
            "llm_calls_used": used,
        }
    )
    return previous_state, stop_state


def reply_ideation_conversation(
    *,
    previous_state: IdeationConvState,
    user_message: str,
    llm_call: LLMCall,
    evidence_lookup=None,
    on_progress: IdeationConvProgressCallback | None = None,
) -> IdeationConvState:
    """사용자 답변을 반영해 다음 정지 지점까지 그래프를 이어간다.

    phase에 따라 실제로 벌어지는 일이 다르다(같은 함수로 통일해도 되는 이유는 다음에
    실행할 노드가 이미 phase 자체에 인코딩돼 있기 때문 — apply_user_answer 참고):
      - awaiting_planning_answer 중 호출: 개발 전문가 질문 1개만 만들고 다시 멈춘다
        (요청 4~5번 — 개발 전문가는 사용자가 기획 질문에 답하기 전에는 절대 실행되지 않는다).
      - awaiting_developer_answer 중 호출: 두 전문가가 순서대로 보완 의견을 말하고,
        더 물어볼 게 있으면 같은 호출 안에서 다음 질문까지 자동으로 만든 뒤 멈춘다.
      - awaiting_user_decision 중 호출: 사용자가 확정 대신 자유롭게 한 마디 더 남긴
        경우로, 두 전문가가 다시 보완 의견을 말한다.
    """
    if previous_state["phase"] not in REPLYABLE_PHASES:
        raise ValueError(
            f"사용자 답변을 받을 수 없는 phase입니다: {previous_state['phase']!r}. "
            f"허용된 phase: {sorted(REPLYABLE_PHASES)}"
        )

    pending_persona = PHASE_TO_PENDING_PERSONA.get(previous_state["phase"])
    if pending_persona is not None:
        # awaiting_planning_answer/awaiting_developer_answer: 지금 답한 것이 특정 질문에
        # 대한 답변이므로 재질문 여부를 먼저 판정한다(요청 3번). awaiting_user_decision(사용자가
        # 확정 대신 자유롭게 남긴 한마디)에는 이 게이트를 적용하지 않는다 — 특정 질문에 대한
        # 답이 아니라 자유 발언이기 때문이다.
        previous_state, follow_up_state = _apply_answer_sufficiency_gate(
            previous_state=previous_state,
            persona_id=pending_persona,
            user_message=user_message,
            llm_call=llm_call,
        )
        if follow_up_state is not None:
            if on_progress is not None:
                on_progress(_progress(follow_up_state))
            return follow_up_state

    answer_message = _new_user_message(user_message, previous_state["round"])
    state = apply_user_answer(previous_state, answer_message)
    if not is_graph_entry_phase(state["phase"]):
        # 방어적 점검 — apply_user_answer()는 항상 그래프 진입 가능한 phase로만 전이시키므로
        # 정상 흐름에서는 절대 여기 도달하지 않는다.
        raise AssertionError(f"apply_user_answer가 진입 불가능한 phase를 반환했습니다: {state['phase']!r}")
    graph = assemble_ideation_conversation_graph(llm_call, evidence_lookup=evidence_lookup)
    return _drive_graph(graph, state, on_progress)


def finalize_ideation_conversation(
    *,
    previous_state: IdeationConvState,
    llm_call: LLMCall,
    on_progress: IdeationConvProgressCallback | None = None,
) -> IdeationConvState:
    """사용자가 "주제 확정하고 초안 받기"를 눌렀을 때만 호출된다(요청 9~10항). phase가
    awaiting_user_decision이 아니면 request_finalize()가 ValueError를 던진다 — 호출부
    (API 라우터)가 이를 400으로 변환해야 한다."""
    state = request_finalize(previous_state)
    graph = assemble_ideation_conversation_graph(llm_call)
    return _drive_graph(graph, state, on_progress)
