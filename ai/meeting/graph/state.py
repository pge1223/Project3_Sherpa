# 작성자: 경이
# 목적: LangGraph 회의 워크플로 State 정의 (M3). MTG-001(위원별 독립평가)·MTG-002(위원장 종합)·
#       MTG-004(수정 우선순위)·MTG-006(회의 진행 상태 관리) 요구사항을 하나의 상태 스키마로 표현한다.
#       MTG-003(점수 산정)은 ai/meeting/scoring 계산 결과를 score_result에 그대로 담아 연결한다.
# import: 표준 라이브러리 typing만 사용(외부 의존성 없음). 필드 구조는
#         contracts/schemas/review_output.schema.json v2의 rubric/reviewerResult/scoreResult/
#         chairSummary 정의를 그대로 따른다.

from __future__ import annotations

from typing import Literal, TypedDict

MeetingStage = Literal["준비", "검색", "평가", "종합", "완료"]


class MeetingState(TypedDict):
    """회의 1회 실행 동안 그래프 노드들이 공유하는 상태.

    reviewer_results는 위원별로 격리된 딕셔너리다(MTG-001 "위원 간 결과 공유 전 독립
    평가"). 각 위원 노드는 자신의 결과를 만드는 동안 이 딕셔너리의 다른 위원 항목을
    읽지 않아야 한다 — 이를 지키도록 노드를 연결하는 것은 그래프 조립(M4)의 책임이다.
    """

    meeting_id: str
    domain: str
    stage: MeetingStage
    rubric: dict
    submission: dict
    retrieved_evidence: list[dict]
    committee: list[str]
    reviewer_results: dict[str, dict]
    score_result: dict | None
    chair_summary: dict | None
    top_revisions: list[dict] | None
    failed_node: str | None


def initial_state(
    meeting_id: str,
    domain: str,
    rubric: dict,
    submission: dict,
    committee: list[str],
    retrieved_evidence: list[dict] | None = None,
) -> MeetingState:
    """준비(stage="준비") 단계의 초기 State를 만든다.

    위원별 결과·점수·위원장 종합은 아직 생성 전이라 비워 둔다.
    """
    return MeetingState(
        meeting_id=meeting_id,
        domain=domain,
        stage="준비",
        rubric=rubric,
        submission=submission,
        retrieved_evidence=retrieved_evidence or [],
        committee=committee,
        reviewer_results={},
        score_result=None,
        chair_summary=None,
        top_revisions=None,
        failed_node=None,
    )
