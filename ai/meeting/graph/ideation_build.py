# 작성자: 용준/Claude(2026-07-20)
# 목적: "아이디어 발전 회의(ideation)" LangGraph 그래프 조립. 기존 assemble_meeting_graph
#       (build.py, 완전 병렬 fan-out)와 달리 이 그래프는 순차 실행 + 라운드 반복 루프를
#       가진다 — 실제 대화(상호 참조, 반박/보완)를 만들려면 병렬로는 불가능하고 순차 구조가
#       반드시 필요하다는 조사 결론(계획 문서 참고)을 그대로 구현한 것이다.
# import: langgraph.graph.StateGraph/START/END, 같은 패키지의 ideation_nodes/ideation_state.

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from .ideation_nodes import make_facilitator_node, make_ideation_expert_node, make_synthesis_node
from .ideation_state import IdeationState
from .llm import LLMCall


def _route_on_failure(state: IdeationState) -> str:
    return "failed" if state.get("stage") == "실패" else "ok"


def _route_after_facilitator(state: IdeationState) -> str:
    if state.get("stage") == "실패":
        return "failed"
    return state.get("next_action") or "continue_round"


def assemble_ideation_graph(
    llm_call: LLMCall,
    checkpointer: Any | None = None,
    evidence_lookup=None,
):
    """기획 전문가(planning_expert)/개발 전문가(dev_expert)가 순차로 발언하고, 진행자
    (ideation_facilitator)가 라운드마다 다음 행동을 판단하는 그래프를 조립한다.

    max_rounds는 그래프 구조가 아니라 State(ideation_state.py::initial_ideation_state)가
    들고 있는 값이다 — 무한 루프 방지 로직(facilitator의 강제 finalize)이 State를 읽어
    판단하므로 이 함수는 max_rounds를 인자로 받지 않는다.

    START -> planning_expert -> dev_expert -> planning_expert_revise -> facilitator
      facilitator 이후 conditional:
        - "ask_user"       -> END (state["pending_question"]이 채워진 채로 멈춤 — 요청 9번
                               12항 "정보가 부족하면 억지로 최종 결론을 만들지 않는다")
        - "finalize"       -> synthesis -> END
        - "continue_round" -> planning_expert로 되돌아감(다음 라운드)
      round이 max_rounds에 도달하면 facilitator 노드 자체가 next_action을 "finalize"로
      강제하므로(ideation_nodes.py::make_facilitator_node), 이 그래프는 무한 루프에
      빠지지 않는다.

    각 전문가/진행자 노드가 stage="실패"를 반환하면(LLM 호출 또는 JSON 파싱 실패, 재시도
    후에도 실패) 남은 노드를 건너뛰고 그래프를 즉시 끝낸다(요청 9번 14항 폴백).

    evidence_lookup은 backend/RAG(ai/rag/orchestration/ideation_evidence_service.py)가
    주입하는 Callable(persona_id, topic_query) -> retrieved_evidence다. 없으면(레거시/테스트
    경로) 근거 없이 진행한다 — 이 그래프는 ai/rag를 직접 import하지 않는다(회의 ↔ RAG
    분리 유지, 기존 build.py와 같은 원칙).
    """
    graph = StateGraph(IdeationState)

    planning_node = make_ideation_expert_node("planning_expert", llm_call, evidence_lookup)
    dev_node = make_ideation_expert_node("dev_expert", llm_call, evidence_lookup)
    facilitator_node = make_facilitator_node(llm_call)
    synthesis_node = make_synthesis_node(llm_call)

    graph.add_node("planning_expert", planning_node)
    graph.add_node("dev_expert", dev_node)
    graph.add_node("planning_expert_revise", planning_node)
    graph.add_node("facilitator", facilitator_node)
    graph.add_node("synthesis", synthesis_node)

    graph.add_edge(START, "planning_expert")
    graph.add_conditional_edges(
        "planning_expert", _route_on_failure, {"ok": "dev_expert", "failed": END}
    )
    graph.add_conditional_edges(
        "dev_expert", _route_on_failure, {"ok": "planning_expert_revise", "failed": END}
    )
    graph.add_conditional_edges(
        "planning_expert_revise", _route_on_failure, {"ok": "facilitator", "failed": END}
    )
    graph.add_conditional_edges(
        "facilitator",
        _route_after_facilitator,
        {
            "continue_round": "planning_expert",
            "ask_user": END,
            "finalize": "synthesis",
            "failed": END,
        },
    )
    graph.add_edge("synthesis", END)

    return graph.compile(checkpointer=checkpointer)
