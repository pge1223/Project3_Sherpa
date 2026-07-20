# 작성자: 용준/Claude(2026-07-20)
# 목적: "아이디어 발전 회의(ideation)" LangGraph State 정의. 기존 MeetingState(state.py)는
#       심사형 회의(위원 병렬 fan-out) 전용이라 건드리지 않고, 완전히 별도의 상태를 만든다.
#       기획 전문가/개발 전문가가 순차로 실행되며 서로의 직전 발언을 참조할 수 있어야 하고,
#       라운드가 반복되며(최대 max_rounds) 회의 도중 사용자 질문으로 멈출 수 있어야 한다는
#       점이 기존 MeetingState와의 핵심 차이다.
# import: 표준 라이브러리 typing/operator만 사용(외부 의존성 없음). 필드 구조는
#         contracts/schemas/ideation_output.schema.json(초안)의 meetingTurn/ideaProposal
#         정의를 그대로 따른다.

from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict

IdeationStage = Literal["준비", "진행중", "사용자_대기", "종합", "완료", "실패"]
NextAction = Literal["continue_round", "ask_user", "finalize"]


class IdeationState(TypedDict):
    """회의 1회 실행 동안 그래프 노드들이 공유하는 상태.

    turns는 기획/개발 전문가가 순차로 실행되며 하나씩 이어붙이는 리스트다(리듀서
    operator.add) — 기존 MeetingState.reviewer_results와 달리 "위원별로 격리된 딕셔너리"가
    아니라 "순서가 보존된 리스트"인 이유는, 뒤에 실행되는 전문가가 반드시 앞선 전문가의
    발언(turns[-1])을 읽어야 하기 때문이다(진짜 대화). consensus/unresolved_issues/
    next_action/pending_question/round/stage는 facilitator 노드만 갱신하므로 병렬 충돌이
    없어 리듀서 없이 단순 덮어쓰기로 충분하다.
    """

    meeting_id: str
    notice_and_criteria: dict
    user_idea: dict
    round: int
    max_rounds: int
    turns: Annotated[list[dict], operator.add]
    consensus: list[str]
    unresolved_issues: list[str]
    next_action: NextAction | None
    pending_question: str | None
    user_answer: str | None
    stage: IdeationStage
    idea_proposal: dict | None
    failed_node: str | None


def initial_ideation_state(
    meeting_id: str,
    notice_and_criteria: dict,
    user_idea: dict,
    max_rounds: int = 3,
) -> IdeationState:
    """준비(stage="준비") 단계의 초기 State를 만든다. max_rounds 기본값 3은 무한 반복
    방지(요청 9번 10항)를 위한 그래프 조건부 종료 기준이다."""
    return IdeationState(
        meeting_id=meeting_id,
        notice_and_criteria=notice_and_criteria,
        user_idea=user_idea,
        round=1,
        max_rounds=max_rounds,
        turns=[],
        consensus=[],
        unresolved_issues=[],
        next_action=None,
        pending_question=None,
        user_answer=None,
        stage="준비",
        idea_proposal=None,
        failed_node=None,
    )


def resume_ideation_state(previous_state: IdeationState, user_answer: str) -> IdeationState:
    """사용자 질문 대기(stage="사용자_대기") 상태였던 State에 사용자 답변을 채워
    다음 라운드를 이어갈 수 있게 한다(요청 5번 6~7항). pending_question은 답변을
    받았으므로 비우고, round는 그대로 유지한다 — 답변이 반영된 다음 전문가 발언부터
    새 정보로 이어진다."""
    return IdeationState(
        **{
            **previous_state,
            "user_answer": user_answer,
            "pending_question": None,
            "stage": "진행중",
            "next_action": None,
        }
    )
