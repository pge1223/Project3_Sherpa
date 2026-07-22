# 작성자: 용준/Claude(2026-07-20)
# 목적: 대화형 아이디어 발전 회의(ideation-conversation) LangGraph 그래프 조립.
#
#       배치형(ideation_build.py)과의 핵심 차이: 배치형은 START에서 시작해 한 번의
#       graph.stream()이 여러 노드를 연달아 통과한다. 이 그래프는 반대로 "한 번의
#       graph.stream() 호출에서 보통 딱 하나의 정지 지점까지만 간다" — START 진입 자체를
#       state["phase"]로 분기해서(_route_entry), HTTP 요청 한 번(질문 생성 1건, 또는
#       사용자 답변 반영 후 다음 질문 생성 1건, 또는 두 전문가 보완 의견 1라운드, 또는
#       최종 종합)에 딱 필요한 만큼만 실행한다. 그래서 이 그래프는 매 HTTP 요청마다
#       backend가 새로 assemble해서 쓴다(continue_ideation_meeting()이 매번 그래프를
#       새로 조립하는 것과 같은 패턴 — ideation_run.py 참고).
#
#       유일하게 그래프 내부에서 "정지 없이" 이어지는 구간은 planning_expert_discussion ->
#       dev_expert_discussion(두 전문가가 순서대로 보완 의견을 말하는 구간)과, 다음 라운드로
#       넘어갈 때(dev_expert_discussion이 next_action="continue_round"를 판단해 곧바로
#       planning_question으로 되돌아가는 것)이다 — 사용자 입력 없이 시스템이 스스로
#       진행해도 되는 구간이기 때문이다(요구 7~8번). 최종 확정(synthesis)은 이 루프 안에
#       들어있지 않다 — 오직 별도 API 호출(ideation_conv_run.py::finalize_ideation_conversation)
#       로만 phase="finalizing"을 만들어 진입할 수 있다(요구 9~10번, 임의 확정 금지).
# import: langgraph.graph.StateGraph/START/END, 같은 패키지의 ideation_conv_nodes/state.

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from .ideation_conv_discovery import (
    make_candidate_feasibility_node,
    make_candidate_planning_node,
    make_candidate_selection_node,
)
from .ideation_conv_nodes import (
    REVISION_TRIGGER_STANCES,
    make_conv_discussion_node,
    make_conv_question_node,
    make_conv_synthesis_node,
    make_discussion_facilitator_node,
)
from .ideation_conv_state import IdeationConvState
from .llm import LLMCall

_ENTRY_NODES = {
    # 용준/Claude(2026-07-21): discovery(아이디어 발굴) 모드 진입점 2개 — refinement 전용
    # 진입점(아래 4개)은 값 하나도 바꾸지 않는다.
    "candidate_generation": "candidate_planning",
    "candidate_selection": "candidate_selection",
    "planning_question": "planning_question",
    "developer_question": "developer_question",
    "expert_discussion": "planning_expert_discussion",
    "finalizing": "synthesis",
}


def _route_entry(state: IdeationConvState) -> str:
    """START 직후 phase를 보고 이번 그래프 호출에서 실행할 노드를 고른다. 이 그래프는
    awaiting_*/awaiting_user_decision/finalized/failed phase로는 절대 진입하지 않는다
    (호출부가 그 phase에서는 그래프를 아예 부르지 않아야 한다 — ideation_conv_run.py가
    보장한다)."""
    phase = state.get("phase")
    if phase not in _ENTRY_NODES:
        raise ValueError(
            f"이 phase에서는 그래프를 시작할 수 없습니다: {phase!r}. "
            "awaiting_*/awaiting_user_decision/finalized/failed는 API 레이어가 걸러야 합니다."
        )
    return _ENTRY_NODES[phase]


def _route_after_first_discussion(state: IdeationConvState) -> str:
    return "failed" if state.get("phase") == "failed" else "ok"


def _route_after_review(state: IdeationConvState) -> str:
    """용준/Claude(2026-07-21, 요청: 위원 간 실제 회의로 개편): dev_expert_discussion(review
    단계) 직후 라우팅. dev의 stance가 REVISION_TRIGGER_STANCES에 속할 때만
    planning_expert_revision을 거친다 — "동의"/"보완"처럼 원래 제안을 바꿀 필요가 없는
    반응이면 곧바로 진행자 정리로 건너뛴다(요청 6번 "필요할 때만 수정 의견 1회", 비용 절감).
    """
    if state.get("phase") == "failed":
        return "failed"
    if state.get("discussion_review_stance") in REVISION_TRIGGER_STANCES:
        return "revise"
    return "summarize"


def _route_after_revision(state: IdeationConvState) -> str:
    return "failed" if state.get("phase") == "failed" else "summarize"


def _route_after_facilitator(state: IdeationConvState) -> str:
    """discussion_facilitator는 phase를 절대 바꾸지 않으므로(dev_expert_discussion이 이미
    정한 값을 그대로 둔다), 여기서 보는 phase는 review 단계가 결정한 값 그대로다.

    용준/Claude(2026-07-21, 요청: 전문가 라운드테이블 전환): dev_expert_discussion이
    다음 라운드로 이어가기로 판단하면(phase="planning_question") 그 phase 값은 그대로
    "다음 라운드 시작" 신호로만 쓰고, 실제로는 1:1 인터뷰(planning_question 노드)가 아니라
    라운드테이블(planning_expert_discussion)로 돌아간다 — phase 문자열 자체는 최소 변경
    원칙에 따라 바꾸지 않고 라우팅 목적지만 바꾼다."""
    phase = state.get("phase")
    if phase == "failed":
        return "failed"
    if phase == "planning_question":
        return "continue_round"
    return "await_user_decision"


def _route_after_candidate_planning(state: IdeationConvState) -> str:
    return "failed" if state.get("phase") == "failed" else "ok"


def _route_after_candidate_selection(state: IdeationConvState) -> str:
    """candidate_selection 노드가 반환한 phase를 보고 이번 요청 안에서 더 진행할지 정한다.
    - "planning_question": 선택/결합/추천이 확정됐다 — 같은 요청 안에서 곧바로 refinement의
      첫 질문(기획 전문가 질문)까지 만든다(요청 4번, 사용자 왕복을 하나 아낀다).
    - "candidate_generation": "다시 추천" — 같은 요청 안에서 후보를 다시 만든다.
    - 그 외("awaiting_candidate_selection" 그대로거나 재추천 상한 도달 안내): 정지(END).
    """
    phase = state.get("phase")
    if phase == "failed":
        return "failed"
    if phase == "planning_question":
        return "to_refinement"
    if phase == "candidate_generation":
        return "regenerate"
    return "await_selection"


def assemble_ideation_conversation_graph(
    llm_call: LLMCall,
    checkpointer: Any | None = None,
    evidence_lookup=None,
):
    """대화형 아이디어 발전 회의 그래프를 조립한다.

    노드:
      - planning_question / developer_question: 질문 하나 만들고 바로 END(각각
        awaiting_planning_answer / awaiting_developer_answer로 멈춤).
      - planning_expert_discussion -> dev_expert_discussion: 사용자가 두 질문에 모두
        답한 뒤 두 전문가가 순서대로 보완 의견을 말한다. dev_expert_discussion(항상
        나중에 말함)만 다음 라운드로 갈지(같은 그래프 호출 안에서 planning_question으로
        되돌아감) 사용자 결정을 기다릴지(END) 정한다.
      - synthesis: 사용자가 확정 버튼을 눌렀을 때만(phase="finalizing") 진입.

    max_rounds 강제 종료(무한 루프 방지)는 ideation_conv_nodes.py::make_conv_discussion_node
    안에서 state를 직접 재계산해 판단한다(배치형 facilitator와 같은 원칙 — 그래프 구조가
    아니라 노드가 State를 신뢰의 근거로 삼는다).
    """
    graph = StateGraph(IdeationConvState)

    planning_question_node = make_conv_question_node(
        "planning_expert", "awaiting_planning_answer", llm_call, evidence_lookup
    )
    developer_question_node = make_conv_question_node(
        "dev_expert", "awaiting_developer_answer", llm_call, evidence_lookup
    )
    planning_discussion_node = make_conv_discussion_node(
        "planning_expert", speaks_second=False, llm_call=llm_call, evidence_lookup=evidence_lookup,
        discussion_stage="initial_position",
    )
    dev_discussion_node = make_conv_discussion_node(
        "dev_expert", speaks_second=True, llm_call=llm_call, evidence_lookup=evidence_lookup,
        discussion_stage="review",
    )
    # 용준/Claude(2026-07-21, 요청: 위원 간 실제 회의로 개편) — planning_expert가 dev_expert의
    # 구체적 우려에 수정/유지로 응답하는 조건부 노드(REVISION_TRIGGER_STANCES일 때만 실행,
    # _route_after_review 참고). speaks_second=False로 만든다 — 라운드를 끝낼지 여부는 이미
    # review 단계가 결정했으므로 이 노드는 phase를 건드리지 않는다.
    planning_revision_node = make_conv_discussion_node(
        "planning_expert", speaks_second=False, llm_call=llm_call, evidence_lookup=evidence_lookup,
        discussion_stage="revision",
    )
    discussion_facilitator_node = make_discussion_facilitator_node(llm_call)
    synthesis_node = make_conv_synthesis_node(llm_call)

    # 용준/Claude(2026-07-21): discovery(아이디어 발굴) 모드 노드 3종.
    candidate_planning_node = make_candidate_planning_node(llm_call, evidence_lookup)
    candidate_feasibility_node = make_candidate_feasibility_node(llm_call, evidence_lookup)
    candidate_selection_node = make_candidate_selection_node(llm_call, evidence_lookup)

    graph.add_node("planning_question", planning_question_node)
    graph.add_node("developer_question", developer_question_node)
    graph.add_node("planning_expert_discussion", planning_discussion_node)
    graph.add_node("dev_expert_discussion", dev_discussion_node)
    graph.add_node("planning_expert_revision", planning_revision_node)
    graph.add_node("discussion_facilitator", discussion_facilitator_node)
    graph.add_node("synthesis", synthesis_node)
    graph.add_node("candidate_planning", candidate_planning_node)
    graph.add_node("candidate_feasibility", candidate_feasibility_node)
    graph.add_node("candidate_selection", candidate_selection_node)

    graph.set_conditional_entry_point(
        _route_entry,
        {
            "candidate_planning": "candidate_planning",
            "candidate_selection": "candidate_selection",
            "planning_question": "planning_question",
            "developer_question": "developer_question",
            "planning_expert_discussion": "planning_expert_discussion",
            "synthesis": "synthesis",
        },
    )

    graph.add_edge("planning_question", END)
    graph.add_edge("developer_question", END)

    graph.add_conditional_edges(
        "planning_expert_discussion",
        _route_after_first_discussion,
        {"ok": "dev_expert_discussion", "failed": END},
    )
    graph.add_conditional_edges(
        "dev_expert_discussion",
        _route_after_review,
        {
            "revise": "planning_expert_revision",
            "summarize": "discussion_facilitator",
            "failed": END,
        },
    )
    graph.add_conditional_edges(
        "planning_expert_revision",
        _route_after_revision,
        {"summarize": "discussion_facilitator", "failed": END},
    )
    graph.add_conditional_edges(
        "discussion_facilitator",
        _route_after_facilitator,
        {
            # 용준/Claude(2026-07-21, 요청: 전문가 라운드테이블 전환) — 다음 라운드도 1:1
            # 인터뷰(planning_question)가 아니라 라운드테이블(planning_expert_discussion)로
            # 곧바로 이어간다.
            "continue_round": "planning_expert_discussion",
            "await_user_decision": END,
            "failed": END,
        },
    )
    graph.add_edge("synthesis", END)

    # discovery: candidate_planning -> candidate_feasibility(성공 시, 정지 없이 이어짐) ->
    # END(awaiting_candidate_selection으로 멈춤). candidate_selection은 선택 확정 시
    # planning_question으로(같은 요청 안에서 refinement 첫 질문까지 생성), 재추천 요청 시
    # candidate_planning으로 되돌아가고(같은 요청 안에서 새 후보 생성), 그 외에는 END.
    graph.add_conditional_edges(
        "candidate_planning",
        _route_after_candidate_planning,
        {"ok": "candidate_feasibility", "failed": END},
    )
    graph.add_edge("candidate_feasibility", END)
    graph.add_conditional_edges(
        "candidate_selection",
        _route_after_candidate_selection,
        {
            # 용준/Claude(2026-07-21, 요청: 전문가 라운드테이블 전환) — 후보 확정 직후에도
            # 1:1 인터뷰가 아니라 라운드테이블로 바로 들어간다(refinement 시작과 동일한
            # 원칙). 안건 제시 메시지는 ideation_conv_discovery.py의 후보 확정 지점이
            # build_roundtable_opening_message로 미리 붙여 둔다.
            "to_refinement": "planning_expert_discussion",
            "regenerate": "candidate_planning",
            "await_selection": END,
            "failed": END,
        },
    )

    return graph.compile(checkpointer=checkpointer)
