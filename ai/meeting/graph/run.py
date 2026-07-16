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

# 재인/Claude(2026-07-16): media_script(위원 발언 영상 대본) 채우기. 새 LLM 호출이나
# 프롬프트 변경 없이, 이미 만들어진 reviewer_results(summary/persona_name)를 그대로
# 재포장한다.
#
# 전체 위원을 다 넣는다 - voice_map.json에 목소리가 매핑된 위원만 거르지 않는다.
# (처음엔 여기서 걸렀었는데, MeetingChat.jsx가 media_script가 비어있지 않으면
# 그걸 텍스트 채팅 소스로 우선 쓰도록 돼있어서, 여기서 일부만 넣으면 텍스트
# 채팅에도 그 일부만 보이는 부작용이 생겼다 - 실측 확인. "실제 아바타 영상을
# 만들지 말지"는 CommitteeVideoStage.jsx가 available-speakers로 이미 따로
# 걸러내고 있으니, 여기서는 위원 전체를 그대로 다 담는다.)
def _build_media_script(reviewer_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    for reviewer in reviewer_results:
        lines.append(
            {
                "speaker_id": reviewer["persona_id"],
                "speaker_name": reviewer["persona_name"],
                "order": len(lines) + 1,
                "text": reviewer["summary"],
                # emotion은 아직 계산하는 곳이 없어서 일단 고정값 - 추후 판단 필요(재인 확인 예정)
                "emotion": "neutral",
            }
        )
    return lines


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

    media_script(위원 발언 영상 대본)는 _build_media_script()(재인/Claude, 2026-07-16
    추가, 위 참고)가 reviewer_results를 재포장해서 채운다 - 원래는 "영상 대본 생성은
    이 함수 책임 아님"이라 비워뒀었는데(경이, 2026-07-15), 재인 쪽 자료(voice_map.json,
    contracts/schemas/media_stream.schema.md)가 준비돼서 이제 여기서 직접 채운다.
    """
    # 가은/Claude(2026-07-16): reviewer_results 조립 시 딕셔너리 "값"의 persona_id 필드가
    # 아니라 "키"를 신뢰해서 덮어쓰도록 수정. final_state["reviewer_results"]는
    # {실제 committee persona_id: v2_result} 딕셔너리인데, v2_result 내부의 "persona_id"는
    # LLM이 raw JSON으로 반환한 값을 거의 그대로 옮긴 거라 신뢰할 수 없다 — 실제 OpenAI
    # 호출로 확인(예: "business_strategy" 대신 "P-STRATEGY-01" 같은 걸 지어냄).
    # rerun_reviewer()(rerun.py)가 이 값의 persona_id로 재평가 대상을 걸러내는데
    # (kept_results = {r["persona_id"]: r ... if r["persona_id"] != persona_id}), 수정 전
    # 코드로는 그 필터가 항상 실패해서(지어낸 값이 실제 committee id와 절대 안 같음)
    # reevaluate를 부를 때마다 위원이 교체되지 않고 계속 추가되기만 하는 걸 실제로
    # 재현해서 확인했다(committee 4명인데 reevaluate 1번에 reviewer_results가 5개로 늘어남).
    reviewer_results = [
        {**v2_result, "persona_id": persona_id}
        for persona_id, v2_result in final_state["reviewer_results"].items()
    ]
    return {
        "schema_version": "2.0.0",
        "meeting_id": meeting_id,
        "project_id": project_id,
        "document_id": document_id,
        "title": title,
        "status": "completed",
        "domain": domain,
        "rubric": final_state["rubric"],
        "reviewer_results": reviewer_results,
        "score_result": final_state["score_result"],
        "chair_summary": final_state["chair_summary"],
        "top_revisions": final_state["top_revisions"],
        "evidence": final_state["evidence"],
        "media_script": _build_media_script(reviewer_results),  # 재인/Claude(2026-07-16) - 위 함수 정의부 참고
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
    evidence_context: list[dict[str, Any]] | None = None,
    evidence_callback: Callable[[str, str, dict], dict] | None = None,
) -> dict[str, Any]:
    """회의 1회를 처음부터 끝까지 실행하고 review_output.schema.json v2 문서를 반환한다.

    domain은 rubric_mapping.meta.domain에서 그대로 가져온다 — 호출부가 rubric_mapping과
    다른 domain을 따로 넘길 이유가 없다(둘이 어긋나면 그 자체가 버그다).

    on_progress가 주어지면 그래프의 각 단계(superstep)가 끝날 때마다 진행 상황 dict로
    호출된다(MTG-006 "긴 작업 중 현재 단계 표시"). 실패 노드부터의 재시도(MTG-006 예외)는
    assemble_meeting_graph에 checkpointer를 넘겨 지원하며, 회의 간 상태 보존은 backend의
    몫이다.

    evidence_context / evidence_callback은 RAG(용준) 연동용이다(둘 다 optional — 없으면
    기존 flat retrieved_evidence 경로로 동일하게 동작한다). evidence_context는
    (persona_id, criterion_id)별 retrieved_evidence + 사전 근거충족도(prompt_guard/allow
    플래그) 목록이고, evidence_callback은 위원 의견 생성 후 (persona_id, criterion_id,
    review_item)로 불려 RAG-004 근거 연결 + RAG-005 최종 판정을 반환한다. backend(윤한)가
    두 값을 넘길 때만 게이팅·근거 교체(A안)가 활성화된다.
    """
    domain = rubric_mapping["meta"]["domain"]
    rubric = build_rubric(rubric_mapping)
    committee = list(rubric_mapping["committee"])

    graph = assemble_meeting_graph(committee, llm_call, evidence_callback=evidence_callback)
    state = initial_state(
        meeting_id=meeting_id,
        domain=domain,
        rubric=rubric,
        submission=submission,
        committee=committee,
        retrieved_evidence=retrieved_evidence,
        evidence_context=evidence_context,
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
