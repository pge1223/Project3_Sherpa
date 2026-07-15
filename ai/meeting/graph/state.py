# 작성자: 경이
# 목적: LangGraph 회의 워크플로 State 정의 (M3, M4에서 병렬 fan-in 병합 규칙 보강).
#       MTG-001(위원별 독립평가)·MTG-002(위원장 종합)·MTG-004(수정 우선순위)·
#       MTG-006(회의 진행 상태 관리) 요구사항을 하나의 상태 스키마로 표현한다.
#       MTG-003(점수 산정)은 ai/meeting/scoring 계산 결과를 score_result에 그대로 담아 연결한다.
# import: 표준 라이브러리 typing/operator만 사용(외부 의존성 없음). 필드 구조는
#         contracts/schemas/review_output.schema.json v2의 rubric/reviewerResult/scoreResult/
#         chairSummary/evidence 정의를 그대로 따른다.

from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict

MeetingStage = Literal["준비", "검색", "평가", "종합", "완료"]


def _merge_reviewer_results(current: dict[str, dict], update: dict[str, dict]) -> dict[str, dict]:
    """위원 노드들이 병렬로 반환하는 {persona_id: reviewerResult} 조각을 합친다.
    LangGraph는 리듀서가 없으면 같은 스텝의 병렬 갱신이 서로를 덮어써 위원 결과가
    유실된다(MTG-001 병렬 독립 평가와 직접 충돌) — 그래서 reviewer_results는 반드시
    이 병합 리듀서를 거쳐야 한다."""
    merged = dict(current)
    merged.update(update)
    return merged


class MeetingState(TypedDict):
    """회의 1회 실행 동안 그래프 노드들이 공유하는 상태.

    reviewer_results는 위원별로 격리된 딕셔너리다(MTG-001 "위원 간 결과 공유 전 독립
    평가"). 각 위원 노드는 자신의 결과를 만드는 동안 이 딕셔너리의 다른 위원 항목을
    읽지 않는다 — 노드는 자신의 persona_id 키만 반환하고, 병합은 위 리듀서가 처리한다.
    evidence도 같은 이유로 리스트 이어붙이기(operator.add) 리듀서를 쓴다(위원마다
    자신이 인용한 근거만 추가하고, 서로의 목록을 읽거나 지우지 않는다).
    """

    meeting_id: str
    domain: str
    stage: MeetingStage
    rubric: dict
    submission: dict
    retrieved_evidence: list[dict]
    committee: list[str]
    reviewer_results: Annotated[dict[str, dict], _merge_reviewer_results]
    evidence: Annotated[list[dict], operator.add]
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
        evidence=[],
        score_result=None,
        chair_summary=None,
        top_revisions=None,
        failed_node=None,
    )
