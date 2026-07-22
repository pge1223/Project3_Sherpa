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
from .ideation_conv_discovery import MAX_CANDIDATE_REGENERATIONS, is_regenerate_request
from .ideation_conv_nodes import (
    PHASE_TO_PENDING_PERSONA,
    REVISION_TRIGGER_STANCES,
    conversation_context_for,
    generate_expert_delegation_facilitator_recommendation,
    generate_expert_delegation_proposal,
    generate_expert_delegation_review,
    is_expert_delegation_request,
    judge_answer_sufficiency,
    make_clarification_message,
    make_expert_delegation_facilitator_message,
    make_expert_delegation_message,
    make_expert_delegation_review_message,
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


def _new_user_message(content: str, round_number: int, message_type: str = "answer") -> ConvMessage:
    """사용자 발언 메시지를 조립한다. speaker_id="user"는 persona_cards.json에 없는
    값이라 ideation_conv_nodes.py의 페르소나 기반 헬퍼를 재사용할 수 없어 여기서 직접
    만든다 — message_id/created_at은 다른 메시지와 동일하게 항상 서버가 만든다.

    message_type(용준/Claude(2026-07-21, 요청: 전문가 라운드테이블 전환)은 기본값 "answer"
    (기존 동작 그대로)에 더해 "interjection"을 받을 수 있다 — 호출부(아래
    _reply_message_type_for)가 "진행자가 실제로 물은 질문에 답한 것"과 "라운드 사이에
    자발적으로 끼어든 것"을 구분해 넘긴다(요청 6번)."""
    return ConvMessage(
        message_id=f"MSG-{uuid.uuid4().hex[:10]}",
        speaker_id="user",
        speaker_name="사용자",
        role="사용자",
        round=round_number,
        message_type=message_type,  # type: ignore[typeddict-item]
        content=content,
        referenced_message_ids=[],
        evidence=[],
        created_at=datetime.now(timezone.utc).isoformat(),
        structured=None,
    )


def _reply_message_type_for(previous_state: IdeationConvState) -> str:
    """용준/Claude(2026-07-21, 요청: 전문가 라운드테이블 전환): "awaiting_user_decision"
    (라운드테이블이 한 라운드를 마치고 멈춘 지점)에서만 "answer"/"interjection"을 구분한다.
    진행자가 needs_user_decision=True로 실제 질문을 던졌으면(pending_question이 설정됨)
    "answer", 아니면(사용자가 답할 의무 없이 자발적으로 끼어든 것) "interjection"이다.
    다른 phase(awaiting_planning_answer/awaiting_developer_answer/awaiting_candidate_selection
    — 인터뷰·후보 선택 흐름)는 기존 그대로 항상 "answer"다(요청 범위 밖, 동작 변경 없음)."""
    if previous_state["phase"] == "awaiting_user_decision":
        return "answer" if previous_state.get("pending_question") else "interjection"
    return "answer"


def _new_facilitator_message(content: str, round_number: int) -> ConvMessage:
    """후보 재생성 상한 안내와 같이 그래프 노드를 거치지 않고 바로
    반환해야 하는 진행자 메시지를 만든다."""
    return ConvMessage(
        message_id=f"MSG-{uuid.uuid4().hex[:10]}",
        speaker_id="ideation_facilitator",
        speaker_name="회의 진행자",
        role="진행자",
        round=round_number,
        message_type="summary",
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


_DELEGATION_COUNTERPART = {"planning_expert": "dev_expert", "dev_expert": "planning_expert"}


def _delegate_to_expert(
    *,
    previous_state: IdeationConvState,
    persona_id: str,
    pending_question: str,
    llm_call: LLMCall,
    evidence_lookup,
    context: dict[str, Any],
) -> tuple[IdeationConvState, IdeationConvState | None, list[ConvMessage]]:
    """용준/Claude(2026-07-21, 요청: "모르겠다" UX 개선 + 2026-07-21 후속 요청: expert_delegation도
    위원 간 상호 검토로 확장): 사용자가 pending_question에 답하는 대신 전문가 판단에
    위임했을 때(answer_type="expert_delegation") 단일 위원 제안으로 끝내지 않고, 담당
    위원 제안 -> 반대 위원 검토(REVIEW_TRIGGER_STANCES에 속하면 담당 위원의 수정까지) ->
    진행자 최종 권고안까지 만든다. 같은 질문을 반복하지 않고 다음 단계로 진행해야 하므로
    (요청 사항), 이 처리는 answer_type="answer"와 같은 원칙을 공유한다 — pending_question_topic을
    resolved_topics에 추가하고 answer_retry_count를 리셋한다(reply_ideation_conversation이
    이어서 apply_user_answer로 phase를 넘긴다). 진행자 최종 권고안(facilitator_message)의
    출력 스키마에는 애초에 사용자 재질문 필드가 없어 구조적으로 같은 질문을 반복할 수 없다.

    반환값은 _apply_answer_sufficiency_gate와 같은 3-tuple 계약을 따르되, 세 번째 값이
    이제 리스트다(요청: 여러 위원 발언을 순서대로 끼워 넣어야 하므로) — 성공하면
    (다음에 apply_user_answer에 넘길 previous_state, None, [제안, 검토, (있으면) 수정,
    진행자 권고안] 메시지 목록), 어느 단계든 구조화 검증에 실패하면(재시도 후에도 무효)
    (previous_state, phase="failed"인 최종 state, []) — 다른 콘텐츠 생성 노드(질문/의견
    턴)의 구조화 검증 실패와 동일한 정책이다."""
    query = pending_question or _topic_query_fallback(previous_state)
    used = previous_state.get("llm_calls_used", 0)

    def _fail(node_name: str, attempts: int) -> tuple[IdeationConvState, IdeationConvState | None, list[ConvMessage]]:
        nonlocal used
        used += attempts
        failed_state = IdeationConvState(
            **{**previous_state, "phase": "failed", "failed_node": node_name, "llm_calls_used": used}
        )
        return previous_state, failed_state, []

    # 1) 담당 위원의 최초 제안.
    owner_retrieved = evidence_lookup(persona_id, query) if evidence_lookup is not None else []
    proposal_raw, ok, attempts = generate_expert_delegation_proposal(
        llm_call,
        persona_id,
        pending_question,
        previous_state["notice_and_criteria"],
        previous_state["user_idea"],
        owner_retrieved,
        context,
    )
    if not ok or proposal_raw is None:
        return _fail(f"expert_delegation__{persona_id}", attempts)
    used += attempts

    known_ids = {m["message_id"] for m in previous_state["messages"]}
    proposal_message = make_expert_delegation_message(
        persona_id=persona_id,
        round_number=previous_state["round"],
        proposal=proposal_raw["proposal"],
        reason=proposal_raw["reason"],
        assumption=proposal_raw["assumption"],
        referenced_message_ids=proposal_raw.get("referenced_message_ids"),
        evidence=proposal_raw.get("evidence"),
        known_message_ids=known_ids,
    )
    messages = [proposal_message]
    known_ids = known_ids | {proposal_message["message_id"]}

    # 2) 반대 위원의 검토(용준/Claude(2026-07-21), 요청: expert_delegation도 위원 간 상호
    #    검토로 확장) — 사용자가 아니라 동료 전문가로서 제안을 검토한다.
    counterpart_id = _DELEGATION_COUNTERPART[persona_id]
    counterpart_retrieved = evidence_lookup(counterpart_id, query) if evidence_lookup is not None else []
    review_raw, ok, attempts = generate_expert_delegation_review(
        llm_call,
        counterpart_id,
        pending_question,
        previous_state["notice_and_criteria"],
        previous_state["user_idea"],
        counterpart_retrieved,
        context,
        proposal_raw,
    )
    if not ok or review_raw is None:
        return _fail(f"expert_delegation_review__{counterpart_id}", attempts)
    used += attempts

    review_message = make_expert_delegation_review_message(
        persona_id=counterpart_id, round_number=previous_state["round"], raw=review_raw, known_message_ids=known_ids
    )
    messages.append(review_message)
    known_ids = known_ids | {review_message["message_id"]}

    # 3) 반대 위원의 stance가 REVISION_TRIGGER_STANCES(반박/조건부_동의/대안_제시)에 속할
    #    때만 담당 위원이 수정/유지 의견을 낸다(요청 6번과 동일한 비용 절감 원칙 — 새 분류
    #    LLM 호출 없이 이미 나온 stance 필드만으로 결정적으로 게이팅한다).
    revision_raw: dict | None = None
    if review_raw.get("stance") in REVISION_TRIGGER_STANCES:
        revision_retrieved = evidence_lookup(persona_id, query) if evidence_lookup is not None else []
        revision_raw, ok, attempts = generate_expert_delegation_proposal(
            llm_call,
            persona_id,
            pending_question,
            previous_state["notice_and_criteria"],
            previous_state["user_idea"],
            revision_retrieved,
            context,
            stage="revision",
            counterpart_review=review_raw,
        )
        if not ok or revision_raw is None:
            return _fail(f"expert_delegation__{persona_id}", attempts)
        used += attempts

        revision_message = make_expert_delegation_message(
            persona_id=persona_id,
            round_number=previous_state["round"],
            proposal=revision_raw["proposal"],
            reason=revision_raw["reason"],
            assumption=revision_raw["assumption"],
            referenced_message_ids=revision_raw.get("referenced_message_ids"),
            evidence=revision_raw.get("evidence"),
            known_message_ids=known_ids,
            responding_to=revision_raw.get("responding_to"),
            revision=revision_raw.get("revision"),
        )
        messages.append(revision_message)

    # 4) 진행자 최종 권고안 — 스키마에 사용자 재질문 필드가 아예 없어 같은 질문을 반복할 수
    #    없다(요청: "다시 사용자에게 같은 질문을 넘기면 안 됩니다").
    facilitator_raw, ok, attempts = generate_expert_delegation_facilitator_recommendation(
        llm_call,
        previous_state["notice_and_criteria"],
        pending_question,
        proposal_raw,
        review_raw,
        revision_raw,
    )
    if not ok or facilitator_raw is None:
        return _fail("expert_delegation_facilitator", attempts)
    used += attempts

    facilitator_message = make_expert_delegation_facilitator_message(
        round_number=previous_state["round"], raw=facilitator_raw
    )
    messages.append(facilitator_message)

    resolved_topics = list(previous_state.get("resolved_topics") or [])
    pending_topic = previous_state.get("pending_question_topic")
    if pending_topic and pending_topic not in resolved_topics:
        resolved_topics = resolved_topics + [pending_topic]

    # 임시 가정 기록은 이제 진행자의 최종 권고안을 기준으로 남긴다(요청 사항 그대로 보존 —
    # 여전히 unresolved_issues에 "임시 가정"으로 추가되지만, 여러 위원이 검토한 뒤의
    # 최종 결론을 담아야 다음 질문 프롬프트가 더 정확한 맥락을 받는다).
    assumption_note = (
        f"{persona_id}: '{pending_question}'에 대해 사용자가 판단을 위임해 위원 간 검토를 거친 "
        f"다음 임시 가정으로 진행합니다 — {facilitator_raw['final_recommendation']}"
    )
    updated_unresolved = previous_state["unresolved_issues"]
    if assumption_note not in updated_unresolved:
        updated_unresolved = updated_unresolved + [assumption_note]

    next_previous_state = IdeationConvState(
        **{
            **previous_state,
            "resolved_topics": resolved_topics,
            "unresolved_issues": updated_unresolved,
            "llm_calls_used": used,
        }
    )
    return next_previous_state, None, messages


def _topic_query_fallback(state: IdeationConvState) -> str:
    """pending_question이 비어 있을 때만 쓰는 대체 RAG 질의문 — user_idea를 그대로
    텍스트로 이어붙인다(ideation_conv_nodes.py::_topic_query와 같은 원칙이지만, 그 함수는
    비공개 헬퍼라 이 모듈에서 다시 만든다)."""
    idea = state.get("user_idea")
    if isinstance(idea, dict):
        return " ".join(str(v) for v in idea.values() if v)
    return str(idea or "")


def _apply_answer_sufficiency_gate(
    *,
    previous_state: IdeationConvState,
    persona_id: str,
    user_message: str,
    llm_call: LLMCall,
    evidence_lookup=None,
) -> tuple[IdeationConvState, IdeationConvState | None, list[ConvMessage]]:
    """사용자가 pending_question에 방금 남긴 메시지가 답변인지, 설명 요청인지, 불충분한
    답변인지, 전문가에게 판단을 위임한 것인지 판정하고 그에 맞게 처리한다(요청 3번 + 용어
    설명 요청을 재질문으로 오판하지 않기 + "모르겠다" UX 개선).

    반환값은 (다음에 apply_user_answer에 넘길 previous_state, 그래프를 돌리지 않고 즉시
    끝낼 최종 state-또는-None, apply_user_answer 직후 메시지 목록에 추가로 끼워 넣을 전문가
    위임 제안 메시지-또는-None) 3-tuple이다:
      - answer_type="answer"이거나 같은 쟁점 재질문이 이미 상한(_MAX_ANSWER_RETRY)에
        도달했으면 두 번째 값은 None이다 — 호출부가 이어서 apply_user_answer + 그래프 실행을
        정상 진행한다(요청 5번: 상한 도달 시 판정 결과와 무관하게 강제로 다음 단계로 진행,
        이때 판정이 여전히 insufficient_answer였다면 그 사실을 unresolved_issues에 "합리적
        가정"으로 남겨 둔다). 세 번째 값은 None이다.
      - answer_type="clarification_request"이면, 사용자의 요청 메시지와 설명+선택지+재질문을
        담은 명확화 응답을 메시지로 추가한 최종 state를 두 번째 값으로 반환한다. pending_question/
        pending_expected_answer_type/answer_retry_count는 전혀 바뀌지 않는다 — 사용자가 아직
        원래 질문에 답하지 않았을 뿐, 불충분한 답을 한 것이 아니기 때문이다(요청: 재질문
        횟수를 늘리지 않는다). 세 번째 값은 None이다.
      - answer_type="insufficient_answer"이고 아직 상한에 도달하지 않았으면, 사용자의 답변과
        좁혀진 재질문을 메시지로 추가한 최종 state를 두 번째 값으로 반환한다. 세 번째 값은
        None이다.
      - answer_type="expert_delegation"(용준/Claude(2026-07-21), 요청: "모르겠다" UX
        개선)이면 _delegate_to_expert()에 위임한다 — 사용자가 답 대신 전문가 판단에
        맡겼으므로 같은 질문을 반복하지 않고 다음 단계로 진행해야 한다(answer와 같은
        control-flow). 세 번째 값(전문가 제안 메시지)이 채워진다. 제안 생성 자체가
        실패하면 다른 콘텐츠 생성 노드와 동일하게 phase="failed"로 끝난다(두 번째 값).
      호출부는 두 번째 값이 있으면 그래프를 전혀 실행하지 않고(정지 지점을 새로 만들지 않고)
      그 state를 그대로 돌려준다.

    resolved_topics(요청: 질문 주제 구조화)는 answer_type이 "answer" 또는
    "expert_delegation"일 때만 pending_question_topic을 추가한다 — clarification_request/
    insufficient_answer(재질문 진행 중이든 상한 도달로 강제 진행하든)는 사용자가 그 주제에
    실제로 명확히 답하거나 위임한 게 아니므로 resolved로 표시하지 않는다(요청 3번 그대로).

    용준/Claude(2026-07-21, 요청: "모르겠다" UX 개선): 명시적인 위임 표현은 작은 모델이
    잘못 분류하지 않도록 judge_answer_sufficiency(LLM 판정) 호출 자체보다 먼저 결정적
    규칙(is_expert_delegation_request)으로 감지한다 — 매칭되면 sufficiency LLM 호출을
    아예 건너뛴다.
    """
    pending_question = previous_state.get("pending_question") or ""
    expected_answer_type = previous_state.get("pending_expected_answer_type")
    retry_count = previous_state.get("answer_retry_count", 0)
    context = conversation_context_for(previous_state)

    if is_expert_delegation_request(user_message):
        return _delegate_to_expert(
            previous_state=previous_state,
            persona_id=persona_id,
            pending_question=pending_question,
            llm_call=llm_call,
            evidence_lookup=evidence_lookup,
            context=context,
        )

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

    if answer_type == "expert_delegation":
        return _delegate_to_expert(
            previous_state=IdeationConvState(**{**previous_state, "llm_calls_used": used}),
            persona_id=persona_id,
            pending_question=pending_question,
            llm_call=llm_call,
            evidence_lookup=evidence_lookup,
            context=context,
        )

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
        return previous_state, stop_state, []

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
        return next_previous_state, None, []

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
    return previous_state, stop_state, []


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

    # discovery 세션에서는 후보를 선택한 뒤 기획/개발 질문으로 넘어간
    # 상태에서도 "아이디어 다시 짜줘" 의도를 최우선으로 처리한다. 이 가드가
    # 재질문 충분성 판정보다 먼저 실행되어야 재생성 요청을 "질문에 대한
    # 불충분한 답변"으로 오판해 동일한 질문을 반복하지 않는다.
    if (
        previous_state.get("ideation_mode") == "discovery"
        and previous_state["phase"] != "awaiting_candidate_selection"
        and is_regenerate_request(user_message)
    ):
        regeneration_count = previous_state.get("candidate_regeneration_count", 0)
        answer_message = _new_user_message(user_message, previous_state["round"])
        if regeneration_count >= MAX_CANDIDATE_REGENERATIONS:
            notice = _new_facilitator_message(
                f"후보 재추천은 최대 {MAX_CANDIDATE_REGENERATIONS}회까지 가능합니다. "
                "현재 아이디어를 계속 발전시키거나 새 회의를 시작해 주세요.",
                previous_state["round"],
            )
            capped_state = IdeationConvState(
                **{
                    **previous_state,
                    "messages": previous_state["messages"] + [answer_message, notice],
                }
            )
            if on_progress is not None:
                on_progress(_progress(capped_state))
            return capped_state

        restart_state = IdeationConvState(
            **{
                **previous_state,
                "messages": previous_state["messages"] + [answer_message],
                "phase": "candidate_generation",
                "round": 1,
                "pending_question": None,
                "pending_expected_answer_type": None,
                "pending_question_topic": None,
                "resolved_topics": [],
                "consensus": [],
                "unresolved_issues": [],
                "idea_proposal": None,
                "failed_node": None,
                "answer_retry_count": 0,
                "selected_idea": None,
                "selection_reason": None,
                "selection_intent": None,
                "user_selection_message": None,
                "source_candidates": [],
                "merge_analysis": None,
                "candidate_regeneration_count": regeneration_count + 1,
            }
        )
        graph = assemble_ideation_conversation_graph(llm_call, evidence_lookup=evidence_lookup)
        return _drive_graph(graph, restart_state, on_progress)

    pending_persona = PHASE_TO_PENDING_PERSONA.get(previous_state["phase"])
    extra_message: ConvMessage | None = None
    if pending_persona is not None:
        # awaiting_planning_answer/awaiting_developer_answer: 지금 답한 것이 특정 질문에
        # 대한 답변이므로 재질문 여부를 먼저 판정한다(요청 3번). awaiting_user_decision(사용자가
        # 확정 대신 자유롭게 남긴 한마디)에는 이 게이트를 적용하지 않는다 — 특정 질문에 대한
        # 답이 아니라 자유 발언이기 때문이다.
        previous_state, follow_up_state, extra_messages = _apply_answer_sufficiency_gate(
            previous_state=previous_state,
            persona_id=pending_persona,
            user_message=user_message,
            llm_call=llm_call,
            evidence_lookup=evidence_lookup,
        )
        if follow_up_state is not None:
            if on_progress is not None:
                on_progress(_progress(follow_up_state))
            return follow_up_state
    else:
        extra_messages = []

    answer_message = _new_user_message(
        user_message, previous_state["round"], message_type=_reply_message_type_for(previous_state)
    )
    state = apply_user_answer(previous_state, answer_message)
    if extra_messages:
        # 전문가 위임 제안 흐름(요청: "모르겠다" UX 개선 + 위원 간 상호 검토 확장) — 사용자의
        # 원문 메시지 바로 다음에 [담당 위원 제안, 반대 위원 검토, (있으면) 수정, 진행자
        # 권고안] 순서로 이어지도록, apply_user_answer가 사용자 메시지를 넣은 직후 그대로
        # 끼워 넣는다. 이후 프롬프트(conversation_context_for의 recent_messages)와 최종
        # 종합(synthesis)이 messages 전체를 그대로 참조하므로, 이 발언들도 자연히 그
        # 컨텍스트에 포함된다(요청 8번).
        state = IdeationConvState(**{**state, "messages": state["messages"] + extra_messages})
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
