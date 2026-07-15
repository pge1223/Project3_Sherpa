# 작성자: 경이
# 목적: "실제 회의 실행" 엔트리포인트(M4 후속). rubric_mapping + submission +
#       retrieved_evidence + llm_call을 받아 그래프를 끝까지 돌리고
#       review_output.schema.json v2 문서 전체를 조립해 반환한다. backend(윤한)의
#       analyze_project()가 이 함수 하나만 호출하면 되도록 만들었다
#       (backend/app/api/routes/meetings.py 상단 주석 "M4 그래프 준비되면 analyze()
#       내부만 교체" 참고). on_progress 콜백으로 회의 진행 단계를 실시간 통지한다(MTG-006).
# import: 표준 라이브러리 typing, 같은 패키지의 build/rubric/state/llm.

from __future__ import annotations

from typing import Any, Callable

from .build import assemble_meeting_graph
from .llm import LLMCall
from .rubric import build_rubric
from .state import MeetingState, initial_state

# 회의 진행 상황 콜백: {stage, reviews_done, reviews_total, score_done, chair_done}
ProgressCallback = Callable[[dict], None]


def _progress(snapshot: MeetingState, total_reviewers: int) -> dict:
    """State 스냅샷에서 프론트 진행률 표시에 필요한 최소 정보를 뽑는다(MTG-006)."""
    return {
        "stage": snapshot.get("stage"),
        "reviews_done": len(snapshot.get("reviewer_results") or {}),
        "reviews_total": total_reviewers,
        "score_done": snapshot.get("score_result") is not None,
        "chair_done": snapshot.get("chair_summary") is not None,
    }


def assemble_document(
    *,
    meeting_id: str,
    project_id: str,
    document_id: str,
    title: str,
    domain: str,
    final_state: MeetingState,
) -> dict[str, Any]:
    """그래프 최종 State를 review_output.schema.json v2 문서로 조립한다.

    media_script는 비워 둔다 — 영상 대본 생성(재인)은 이 함수의 책임이 아니다.
    """
    return {
        "schema_version": "2.0.0",
        "meeting_id": meeting_id,
        "project_id": project_id,
        "document_id": document_id,
        "title": title,
        "status": "completed",
        "domain": domain,
        "rubric": final_state["rubric"],
        "reviewer_results": list(final_state["reviewer_results"].values()),
        "score_result": final_state["score_result"],
        "chair_summary": final_state["chair_summary"],
        "top_revisions": final_state["top_revisions"],
        "evidence": final_state["evidence"],
        "media_script": [],
    }


def run_meeting(
    *,
    meeting_id: str,
    project_id: str,
    document_id: str,
    title: str,
    rubric_mapping: dict[str, Any],
    submission: dict[str, Any],
    retrieved_evidence: list[dict[str, Any]],
    llm_call: LLMCall,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """회의 1회를 처음부터 끝까지 실행하고 review_output.schema.json v2 문서를 반환한다.

    domain은 rubric_mapping.meta.domain에서 그대로 가져온다 — 호출부가 rubric_mapping과
    다른 domain을 따로 넘길 이유가 없다(둘이 어긋나면 그 자체가 버그다).

    on_progress가 주어지면 그래프의 각 단계(superstep)가 끝날 때마다 진행 상황 dict로
    호출된다(MTG-006 "긴 작업 중 현재 단계 표시"). 실패 노드부터의 재시도(MTG-006 예외)는
    assemble_meeting_graph에 checkpointer를 넘겨 지원하며, 회의 간 상태 보존은 backend의
    몫이다.
    """
    domain = rubric_mapping["meta"]["domain"]
    rubric = build_rubric(rubric_mapping)
    committee = list(rubric_mapping["committee"])

    graph = assemble_meeting_graph(committee, llm_call)
    state = initial_state(
        meeting_id=meeting_id,
        domain=domain,
        rubric=rubric,
        submission=submission,
        committee=committee,
        retrieved_evidence=retrieved_evidence,
    )

    final_state: MeetingState = state
    for snapshot in graph.stream(state, stream_mode="values"):
        final_state = snapshot
        if on_progress is not None:
            on_progress(_progress(snapshot, len(committee)))

    return assemble_document(
        meeting_id=meeting_id,
        project_id=project_id,
        document_id=document_id,
        title=title,
        domain=domain,
        final_state=final_state,
    )
