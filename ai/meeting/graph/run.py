# 작성자: 경이
# 목적: "실제 회의 실행" 엔트리포인트(M4 후속). rubric_mapping + submission +
#       retrieved_evidence + llm_call을 받아 그래프를 끝까지 돌리고
#       review_output.schema.json v2 문서 전체를 조립해 반환한다. backend(윤한)의
#       analyze_project()가 이 함수 하나만 호출하면 되도록 만들었다
#       (backend/app/api/routes/meetings.py 상단 주석 "M4 그래프 준비되면 analyze()
#       내부만 교체" 참고).
# import: 같은 패키지의 build/rubric/state/llm.

from __future__ import annotations

from typing import Any

from .build import assemble_meeting_graph
from .llm import LLMCall
from .rubric import build_rubric
from .state import initial_state


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
) -> dict[str, Any]:
    """회의 1회를 처음부터 끝까지 실행하고 review_output.schema.json v2 문서를 반환한다.

    domain은 rubric_mapping.meta.domain에서 그대로 가져온다 — 호출부가 rubric_mapping과
    다른 domain을 따로 넘길 이유가 없다(둘이 어긋나면 그 자체가 버그다).
    media_script는 아직 비워 둔다 — 영상 대본 생성(재인)은 이 함수의 책임이 아니다.
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
    result = graph.invoke(state)

    return {
        "schema_version": "2.0.0",
        "meeting_id": meeting_id,
        "project_id": project_id,
        "document_id": document_id,
        "title": title,
        "status": "completed",
        "domain": domain,
        "rubric": result["rubric"],
        "reviewer_results": list(result["reviewer_results"].values()),
        "score_result": result["score_result"],
        "chair_summary": result["chair_summary"],
        "top_revisions": result["top_revisions"],
        "evidence": result["evidence"],
        "media_script": [],
    }
