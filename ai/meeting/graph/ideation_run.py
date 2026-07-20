# 작성자: 용준/Claude(2026-07-20)
# 목적: "아이디어 발전 회의(ideation)" 실행 엔트리포인트. run.py::run_meeting()과 같은
#       역할(그래프 조립 + State 초기화 + 실행 + 최종 문서 조립)을 ideation 그래프에 대해
#       수행한다. contracts/schemas/ideation_output.schema.json(초안) 형태의 문서를 반환한다.
# import: 표준 라이브러리 typing, 같은 패키지의 ideation_build/ideation_state/llm.

from __future__ import annotations

from typing import Any, Callable

from .ideation_build import assemble_ideation_graph
from .ideation_state import IdeationState, initial_ideation_state, resume_ideation_state
from .llm import LLMCall

IdeationProgressCallback = Callable[[dict], None]


def _progress(snapshot: IdeationState) -> dict:
    return {
        "stage": snapshot.get("stage"),
        "round": snapshot.get("round"),
        "max_rounds": snapshot.get("max_rounds"),
        "turns_done": len(snapshot.get("turns") or []),
    }


def _assemble_document(meeting_id: str, project_id: str, final_state: IdeationState) -> dict[str, Any]:
    """그래프 최종 State를 ideation_output.schema.json(초안) 문서로 조립한다.

    stage에 따른 status 매핑:
      "사용자_대기" -> "awaiting_user" (pending_question 채워짐, 회의 재개 대기)
      "완료"       -> "completed" (idea_proposal 채워짐)
      "실패"       -> "failed"
      그 외        -> "in_progress"
    """
    stage_to_status = {
        "사용자_대기": "awaiting_user",
        "완료": "completed",
        "실패": "failed",
    }
    status = stage_to_status.get(final_state.get("stage"), "in_progress")
    return {
        "schema_version": "1.0.0",
        "meeting_id": meeting_id,
        "project_id": project_id,
        "status": status,
        "round": final_state["round"],
        "max_round": final_state["max_rounds"],
        "turns": final_state["turns"],
        "consensus": final_state["consensus"],
        "unresolved_issues": final_state["unresolved_issues"],
        "pending_question": final_state.get("pending_question"),
        "idea_proposal": final_state.get("idea_proposal"),
        "error": (
            {"code": "IDEATION_NODE_FAILED", "message": f"{final_state.get('failed_node')} 노드에서 실패했습니다."}
            if final_state.get("stage") == "실패"
            else None
        ),
    }


def start_ideation_meeting(
    *,
    meeting_id: str,
    project_id: str,
    notice_and_criteria: dict[str, Any],
    user_idea: dict[str, Any],
    llm_call: LLMCall,
    max_rounds: int = 3,
    checkpointer: Any | None = None,
    evidence_lookup=None,
    on_progress: IdeationProgressCallback | None = None,
) -> dict[str, Any]:
    """아이디어 발전 회의를 처음부터 실행한다. 라운드 도중 진행자가 사용자 질문이
    필요하다고 판단하면(next_action="ask_user") 그 지점에서 그래프가 멈추고, 이 함수는
    status="awaiting_user"인 문서를 그대로 반환한다(요청 9번 12항 — 억지로 결론을
    만들지 않는다). 이어서 회의를 재개하려면 continue_ideation_meeting()을 쓴다.
    """
    graph = assemble_ideation_graph(llm_call, checkpointer=checkpointer, evidence_lookup=evidence_lookup)
    state = initial_ideation_state(meeting_id, notice_and_criteria, user_idea, max_rounds=max_rounds)

    final_state: IdeationState = state
    config = {"configurable": {"thread_id": meeting_id}} if checkpointer is not None else None
    stream_kwargs = {"config": config} if config is not None else {}
    for snapshot in graph.stream(state, stream_mode="values", **stream_kwargs):
        final_state = snapshot
        if on_progress is not None:
            on_progress(_progress(snapshot))

    return _assemble_document(meeting_id, project_id, final_state)


def continue_ideation_meeting(
    *,
    meeting_id: str,
    project_id: str,
    previous_state: IdeationState,
    user_answer: str,
    llm_call: LLMCall,
    checkpointer: Any | None = None,
    evidence_lookup=None,
    on_progress: IdeationProgressCallback | None = None,
) -> dict[str, Any]:
    """status="awaiting_user"였던 회의에 사용자 답변을 반영해 다음 라운드부터 이어간다.

    checkpointer 없이도 동작한다 — 호출부(backend)가 previous_state(그래프 스트림의
    마지막 스냅샷, 또는 저장소에서 복원한 값)를 그대로 넘기면 이 함수가 사용자 답변만
    반영해 같은 그래프를 이어서 실행한다. checkpointer를 쓰면(선택) 회의 간 상태를
    LangGraph가 자체적으로 보존한다(기존 assemble_meeting_graph의 checkpointer 패턴과
    같은 방식).
    """
    graph = assemble_ideation_graph(llm_call, checkpointer=checkpointer, evidence_lookup=evidence_lookup)
    state = resume_ideation_state(previous_state, user_answer)

    final_state: IdeationState = state
    config = {"configurable": {"thread_id": meeting_id}} if checkpointer is not None else None
    stream_kwargs = {"config": config} if config is not None else {}
    for snapshot in graph.stream(state, stream_mode="values", **stream_kwargs):
        final_state = snapshot
        if on_progress is not None:
            on_progress(_progress(snapshot))

    return _assemble_document(meeting_id, project_id, final_state)
