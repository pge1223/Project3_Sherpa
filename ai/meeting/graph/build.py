# 작성자: 경이
# 목적: LangGraph 회의 그래프 조립(M4). committee(참여 위원)만큼 reviewer 노드를
#       병렬 fan-out 하고, 전부 끝나면 score -> chair 순서로 합류시킨다. checkpointer를
#       넘기면 노드 단위로 진행 상태가 저장되어, 중간 노드가 실패해도 같은 thread_id로
#       재개하면 성공한 노드는 다시 돌지 않고 실패 지점부터 이어서 실행된다(MTG-006
#       "실패 노드부터 재시도").
# import: langgraph.graph.StateGraph/START/END, 같은 패키지의 llm/nodes/state.

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from .llm import LLMCall
from .nodes import make_chair_node, make_reviewer_node, score_node
from .state import MeetingState


def assemble_meeting_graph(committee: list[str], llm_call: LLMCall, checkpointer: Any | None = None):
    """committee(참여 위원 persona_id 목록)에 맞춰 회의 그래프를 조립하고 컴파일한다.

    START -> reviewer__{persona_id}(병렬, MTG-001) -> score(MTG-003) -> chair(MTG-002/004) -> END

    checkpointer가 주어지면 재개 가능한 그래프로 컴파일한다(MTG-006). backend(윤한)가
    회의 간(HTTP 요청 간) 상태를 이어가려면 langgraph.checkpoint의 Saver(MemorySaver
    또는 영속 Saver)를 넘기고 config={"configurable": {"thread_id": meeting_id}}로 실행하면
    된다.
    """
    graph = StateGraph(MeetingState)

    for persona_id in committee:
        graph.add_node(f"reviewer__{persona_id}", make_reviewer_node(persona_id, llm_call))
    graph.add_node("score", score_node)
    graph.add_node("chair", make_chair_node(llm_call))

    for persona_id in committee:
        graph.add_edge(START, f"reviewer__{persona_id}")
        graph.add_edge(f"reviewer__{persona_id}", "score")
    graph.add_edge("score", "chair")
    graph.add_edge("chair", END)

    return graph.compile(checkpointer=checkpointer)
