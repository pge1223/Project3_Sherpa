# 가은/Claude(2026-07-16): dev 머지(PR #37)로 경이의 ai/meeting/graph/rerun.py
# (rerun_reviewer())가 들어와서 이 모듈은 더 이상 backend/app/api/routes/meetings.py의
# reevaluate_reviewer()에서 쓰지 않는다(교체 사유·상세 비교는 meetings.py 상단 주석과
# pge-devlog.md 2026-07-16 참고). 파일은 지우지 않고 남겨둔다 — 삭제 여부/rerun.py로
# 완전 대체할지는 경이 확인 필요.
#
# 작성자: 가은 (경이 합의, MTG-007)
# 목적: 특정 위원 1명만 재평가하고 score -> chair를 다시 종합한다(MTG-007).
#       "선택 위원 외 기존 결과 유지"가 검수 기준이라, committee 전체를 다시 돌리는
#       assemble_meeting_graph 대신 reviewer 노드 1개짜리 그래프를 새로 조립한다.
#       reviewer_results 병합은 state.py의 _merge_reviewer_results 리듀서가 그대로
#       처리해 다른 위원 항목을 덮어쓰지 않는다 — 여기서 신경 써야 하는 건 evidence뿐이다:
#       evidence는 operator.add(리스트 이어붙이기) 리듀서라 재평가 위원의 예전 근거를
#       먼저 걷어내지 않으면 EvidencePool이 evidence_id를 EV-{persona_id}-001부터 다시
#       매겨서 새 근거가 예전 근거와 나란히(중복 ID 포함) 쌓인다.
# import: langgraph.graph.StateGraph/START/END, 같은 패키지의 llm/nodes/state.

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .llm import LLMCall
from .nodes import make_chair_node, make_reviewer_node, score_node
from .state import MeetingState


def assemble_reevaluation_graph(persona_id: str, llm_call: LLMCall):
    """persona_id 위원 1명만 재실행하고 score -> chair를 재종합하는 그래프를 조립한다.

    START -> reviewer__{persona_id} -> score(MTG-003) -> chair(MTG-002/004) -> END
    """
    graph = StateGraph(MeetingState)
    graph.add_node(f"reviewer__{persona_id}", make_reviewer_node(persona_id, llm_call))
    graph.add_node("score", score_node)
    graph.add_node("chair", make_chair_node(llm_call))

    graph.add_edge(START, f"reviewer__{persona_id}")
    graph.add_edge(f"reviewer__{persona_id}", "score")
    graph.add_edge("score", "chair")
    graph.add_edge("chair", END)

    return graph.compile()


def reevaluation_state(previous: MeetingState, persona_id: str) -> MeetingState:
    """이전 회의 결과(previous)를 재평가 그래프의 시작 state로 바꾼다.

    persona_id 위원의 이전 rubric_scores/evidence만 제거하고 나머지(다른 위원 결과,
    committee, rubric, submission, retrieved_evidence)는 그대로 이어받는다. score_result/
    chair_summary/top_revisions는 재평가 이후 score->chair 노드가 다시 채운다.
    """
    if persona_id not in previous["committee"]:
        raise ValueError(f"{persona_id!r}는 이 회의의 committee에 없습니다: {previous['committee']}")

    stale_evidence_prefix = f"EV-{persona_id}-"
    return MeetingState(
        meeting_id=previous["meeting_id"],
        domain=previous["domain"],
        stage="평가",
        rubric=previous["rubric"],
        submission=previous["submission"],
        retrieved_evidence=previous["retrieved_evidence"],
        committee=previous["committee"],
        reviewer_results={k: v for k, v in previous["reviewer_results"].items() if k != persona_id},
        evidence=[e for e in previous["evidence"] if not e["evidence_id"].startswith(stale_evidence_prefix)],
        score_result=None,
        chair_summary=None,
        top_revisions=None,
        failed_node=None,
    )
