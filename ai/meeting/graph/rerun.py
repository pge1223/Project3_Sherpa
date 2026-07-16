# 작성자: 경이
# 목적: 특정 위원 재실행(MTG-007). 이미 끝난 회의 결과(review_output v2 문서)에서
#       지정한 위원 1명만 다시 평가하고, 그 결과로 점수(score)와 위원장 종합(chair)을
#       재종합한다. 선택 위원 외 다른 위원의 기존 결과는 그대로 유지한다(검수 기준).
#       LLM 재호출은 지정 위원 + 위원장뿐이라, 비용은 "위원 1명 + 위원장"으로 한정된다
#       (예외사항 "비용·버전 차이 안내"는 호출부가 사용자에게 고지).
# import: 표준 라이브러리 typing, 같은 패키지의 build/llm/nodes/rubric/run/state.

from __future__ import annotations

from typing import Any

from .build import assemble_meeting_graph
from .llm import LLMCall
from .nodes import make_reviewer_node
from .run import ProgressCallback, _progress, assemble_document
from .state import initial_state


def rerun_reviewer(
    *,
    previous_document: dict[str, Any],
    persona_id: str,
    rubric_mapping: dict[str, Any],
    submission: dict[str, Any],
    retrieved_evidence: list[dict[str, Any]],
    llm_call: LLMCall,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """previous_document(직전 회의 결과 v2)에서 persona_id 위원만 재평가하고 재종합한다.

    - 지정 위원: reviewer 노드를 다시 실행(새 평가로 교체)
    - 나머지 위원: previous_document의 reviewer_results를 그대로 유지(MTG-007 검수 기준)
    - score/chair: 갱신된 위원 결과 전체로 다시 계산·종합
    """
    committee = list(rubric_mapping["committee"])
    if persona_id not in committee:
        raise ValueError(f"{persona_id!r} 는 이 회의 위원({committee})이 아닙니다.")

    domain = rubric_mapping["meta"]["domain"]
    rubric = previous_document["rubric"]

    # 유지할 위원(지정 위원 제외)의 기존 결과를 미리 채워 둔다 → 이들은 노드를 돌지 않는다.
    kept_results = {
        r["persona_id"]: r
        for r in previous_document["reviewer_results"]
        if r["persona_id"] != persona_id
    }
    kept_evidence = _evidence_of(previous_document, exclude_persona=persona_id)

    # 그래프에는 재실행할 위원 1명만 reviewer 노드로 넣는다(나머지는 State에 이미 있으므로).
    graph = _assemble_single_reviewer_graph(persona_id, committee, llm_call)

    state = initial_state(
        meeting_id=previous_document["meeting_id"],
        domain=domain,
        rubric=rubric,
        submission=submission,
        committee=committee,
        retrieved_evidence=retrieved_evidence,
    )
    state["reviewer_results"] = dict(kept_results)
    state["evidence"] = list(kept_evidence)

    final_state = state
    for snapshot in graph.stream(state, stream_mode="values"):
        final_state = snapshot
        if on_progress is not None:
            on_progress(_progress(snapshot, len(committee)))

    return assemble_document(
        meeting_id=previous_document["meeting_id"],
        project_id=previous_document["project_id"],
        document_id=previous_document["document_id"],
        title=previous_document.get("title", ""),
        domain=domain,
        final_state=final_state,
        # RAG-006 참고자료(v2.1.0)는 재평가로 바뀌지 않으니 이전 문서 값을 그대로 유지한다.
        similar_success_cases=previous_document.get("similar_success_cases"),
    )


def _evidence_of(document: dict[str, Any], *, exclude_persona: str) -> list[dict[str, Any]]:
    """유지 위원들의 근거만 남긴다. EvidencePool이 evidence_id에 persona_id를 접두어로
    넣기 때문에(EV-{persona_id}-NNN), 재실행 위원의 근거를 접두어로 걸러낼 수 있다."""
    prefix = f"EV-{exclude_persona}-"
    return [e for e in document.get("evidence", []) if not e["evidence_id"].startswith(prefix)]


def _assemble_single_reviewer_graph(persona_id: str, committee: list[str], llm_call: LLMCall):
    """지정 위원 1명의 reviewer 노드 + score + chair 로 이루어진 재종합 그래프.

    build.assemble_meeting_graph는 committee 전원의 reviewer 노드를 만들지만, 재실행에서는
    1명만 돌려야 하므로 committee=[persona_id] 로 조립한다. score 노드는 State의
    reviewer_results 전체(유지 위원 + 재실행 위원)를 보고 계산하므로, 유지 위원 결과가
    State에 미리 들어 있으면 그대로 반영된다.
    """
    return assemble_meeting_graph([persona_id], llm_call)
