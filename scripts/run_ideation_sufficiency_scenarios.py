"""
아이디어 발전 회의(ideation) 사용자 메시지 분류(answer/clarification_request/
insufficient_answer) 판정 실제 모델 회귀 스크립트
================================================================================
실제 대화에서 확인된 두 가지 문제가 재발하지 않는지 실제 OpenAI 모델로 확인한다.
  1) "생활비 절감 효과를 중시한다"처럼 pending_question이 요구한 방향성을 명확히 선택한
     답변을, "표현이 추상적이다"라는 이유로 부당하게 재질문한 문제.
  2) "가장 중요한 가치의 종류에는 무엇이 있나요?"처럼 용어 설명을 요청한 메시지를 불충분한
     답변으로 오판해 같은 질문을 그대로 반복한 문제.
pytest 대상이 아니다(ai/meeting/tests/test_ideation_conv_graph.py의 stub 기반 테스트는
"answer_type/expected_answer_type이 state -> 프롬프트로 정확히 전달되고, 판정 결과에 따라
run.py가 올바르게 분기하는지"라는 배선만 검증하고, 실제 분류 품질은 검증하지 않는다 — 이
스크립트가 그 부분을 담당한다).

운영 코드/테스트 코드는 이 스크립트에 의존하지 않는다 (일회성 수동 검증 전용).

실행 (repo 루트에서, review-board conda env):
    OPENAI_API_KEY=sk-...  python scripts/run_ideation_sufficiency_scenarios.py
    (PowerShell) $env:OPENAI_API_KEY="sk-..."; python scripts/run_ideation_sufficiency_scenarios.py

    선택 환경변수:
      IDEATION_TEST_MODEL   기본값 gpt-4o-mini

API 키는 코드에 직접 넣지 않는다 — 반드시 OPENAI_API_KEY 환경변수로만 읽는다.

1단계 — 단위 시나리오(judge_answer_sufficiency 직접 호출, 요청 사항 그대로):
  1. "생활비 절감 효과를 중시한다"                          -> answer
  2. "안전보다 생활비 절감을 우선한다"                       -> answer
  3. "1번이 더 좋다"                                        -> answer
  4. "둘 다 중요한 것 같다"                                  -> insufficient_answer
  5. "잘 모르겠다"(선택 질문)                                -> insufficient_answer
  6. 방향성 질문에 답했지만 세부 기능이 없는 경우              -> answer
  7. 구체적인 기능을 요구한 질문에 방향성만 답한 경우           -> insufficient_answer
  8. (실제 보고된 대화) "사용자의 안전도 중요시되지만..."      -> answer
  9. "가치의 종류에는 무엇이 있나요?"                         -> clarification_request
  10. "예시를 들어주세요"                                    -> clarification_request
  11. "질문이 무슨 뜻인가요?"                                -> clarification_request
  12. "생활비 절감이 중요합니다"                              -> answer
  13. "잘 모르겠습니다"(방향성 질문)                          -> insufficient_answer

2단계 — 실제 대화 흐름 확인(start_ideation_conversation + reply_ideation_conversation을
실제 모델로 끝까지 구동): 설명을 요청하면 재질문 카운터가 늘지 않고 같은 질문을 기다리다가,
이어서 실제로 답하면 재질문 없이 다음 단계로 진행되는지 확인한다.

종료 코드:
    0 = 모든 시나리오가 기대한 판정과 일치
    1 = OPENAI_API_KEY 미설정
    2 = 하나 이상의 단위 시나리오가 기대와 다르게 판정됨(회귀)
    3 = 실제 대화 흐름 확인 실패(재질문 카운터 오증가, 무한 반복, 진행 실패 등)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_MEETING_DIR = _REPO_ROOT / "ai" / "meeting"
if str(_MEETING_DIR) not in sys.path:
    sys.path.insert(0, str(_MEETING_DIR))

MODEL = os.environ.get("IDEATION_TEST_MODEL", "gpt-4o-mini")

# 실제 보고 사례를 그대로 재현한 질문 — "두 아이디어를 결합할 때 중점적으로 고려하고 싶은
# 기능이나 사용자 가치를 하나라도 말씀해 주세요..." (기획 전문가, expected_answer_type=preference).
_COMBINE_PREFERENCE_QUESTION = (
    "두 아이디어를 결합할 때 중점적으로 고려하고 싶은 기능이나 사용자 가치를 하나라도 말씀해 "
    "주세요. 예를 들어 '생활비 절감 효과를 중시한다'처럼 간단한 방향성을 알려 주세요."
)
_CANDIDATE_SELECTION_QUESTION = "제시된 두 후보(1번: 문의 자동응답, 2번: 예약 관리) 중 어느 쪽을 더 발전시키고 싶으신가요?"
_FEATURE_SPEC_QUESTION = (
    "선택하신 방향에서 구현할 핵심 기능을 구체적으로 알려 주세요. 예를 들어 어떤 화면에서 어떤 "
    "입력을 받아 어떤 결과를 보여줄지 단계별로 설명해 주세요."
)
_CORE_VALUE_QUESTION = "이 서비스에서 가장 중요하게 지킬 핵심 가치를 하나만 말씀해 주세요."

# 실제 보고 사례의 "두 후보"에 해당하는 맥락(clarification_request 선택지 근거 자료).
_TWO_CANDIDATES_CONTEXT = [
    {"candidate_id": "candidate_1", "title": "생활비 절감 알리미", "problem": "생활비 절감", "target_user": "1인 가구"},
    {"candidate_id": "candidate_2", "title": "안전 확인 알리미", "problem": "안전 확인", "target_user": "1인 가구"},
]

SCENARIOS = [
    {
        "label": "1. 방향성 예시와 동등한 수준으로 선호를 밝힘",
        "pending_question": _COMBINE_PREFERENCE_QUESTION,
        "expected_answer_type": "preference",
        "user_answer": "생활비 절감 효과를 중시한다",
        "expect_answer_type": "answer",
    },
    {
        "label": "2. 비교 대상 사이의 우선순위를 명시함",
        "pending_question": _COMBINE_PREFERENCE_QUESTION,
        "expected_answer_type": "preference",
        "user_answer": "안전보다 생활비 절감을 우선한다",
        "expect_answer_type": "answer",
    },
    {
        "label": "3. 후보 번호로 명확히 선택함",
        "pending_question": _CANDIDATE_SELECTION_QUESTION,
        "expected_answer_type": "selection",
        "user_answer": "1번이 더 좋다",
        "expect_answer_type": "answer",
    },
    {
        "label": "4. 우선순위를 정하지 않고 둘 다 중요하다고만 답함",
        "pending_question": _COMBINE_PREFERENCE_QUESTION,
        "expected_answer_type": "preference",
        "user_answer": "둘 다 중요한 것 같다",
        "expect_answer_type": "insufficient_answer",
    },
    {
        "label": "5. 선택을 회피함",
        "pending_question": _CANDIDATE_SELECTION_QUESTION,
        "expected_answer_type": "selection",
        "user_answer": "잘 모르겠다",
        "expect_answer_type": "insufficient_answer",
    },
    {
        "label": "6. 방향성 질문에 답했지만 세부 기능은 없음(요구 수준을 넘어서지 않음)",
        "pending_question": _COMBINE_PREFERENCE_QUESTION,
        "expected_answer_type": "preference",
        "user_answer": "생활비 절감을 우선하겠다",
        "expect_answer_type": "answer",
    },
    {
        "label": "7. 구체적 기능을 요구한 질문에 방향성만 답함(요구 수준 미달)",
        "pending_question": _FEATURE_SPEC_QUESTION,
        "expected_answer_type": "specification",
        "user_answer": "생활비 절감 효과를 중시한다",
        "expect_answer_type": "insufficient_answer",
    },
    {
        "label": "8. 실제 보고된 대화 재현",
        "pending_question": _COMBINE_PREFERENCE_QUESTION,
        "expected_answer_type": "preference",
        "user_answer": "사용자의 안전도 중요시되지만, 내 생각에는 생활비 절감 효과를 중시하는 게 더 매력이 있을 것 같아.",
        "expect_answer_type": "answer",
    },
    {
        "label": "9. 용어 설명 요청",
        "pending_question": _CORE_VALUE_QUESTION,
        "expected_answer_type": "preference",
        "user_answer": "가치의 종류에는 무엇이 있나요?",
        "expect_answer_type": "clarification_request",
        "idea_candidates": _TWO_CANDIDATES_CONTEXT,
    },
    {
        "label": "10. 예시 요청",
        "pending_question": _CORE_VALUE_QUESTION,
        "expected_answer_type": "preference",
        "user_answer": "예시를 들어주세요",
        "expect_answer_type": "clarification_request",
        "idea_candidates": _TWO_CANDIDATES_CONTEXT,
    },
    {
        "label": "11. 질문 의미 재확인 요청",
        "pending_question": _CORE_VALUE_QUESTION,
        "expected_answer_type": "preference",
        "user_answer": "질문이 무슨 뜻인가요?",
        "expect_answer_type": "clarification_request",
        "idea_candidates": _TWO_CANDIDATES_CONTEXT,
    },
    {
        "label": "12. 설명 없이 바로 명확히 답함",
        "pending_question": _CORE_VALUE_QUESTION,
        "expected_answer_type": "preference",
        "user_answer": "생활비 절감이 중요합니다",
        "expect_answer_type": "answer",
        "idea_candidates": _TWO_CANDIDATES_CONTEXT,
    },
    {
        "label": "13. 방향성 질문에 회피성 답변",
        "pending_question": _CORE_VALUE_QUESTION,
        "expected_answer_type": "preference",
        "user_answer": "잘 모르겠습니다",
        "expect_answer_type": "insufficient_answer",
        "idea_candidates": _TWO_CANDIDATES_CONTEXT,
    },
]


def make_llm_call():
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    def llm_call(prompt: str) -> str:
        resp = client.chat.completions.create(
            model=MODEL, messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"}
        )
        return resp.choices[0].message.content

    return llm_call


def run_unit_scenarios(llm_call) -> list[str]:
    from graph.ideation_conv_nodes import judge_answer_sufficiency

    empty_context = {"round": 1, "recent_messages": [], "last_user_answer": None, "consensus_so_far": [], "unresolved_issues": []}
    failures: list[str] = []

    for scenario in SCENARIOS:
        result = judge_answer_sufficiency(
            llm_call,
            "planning_expert",
            scenario["pending_question"],
            scenario["user_answer"],
            retry_count=0,
            conversation_context=empty_context,
            expected_answer_type=scenario["expected_answer_type"],
            idea_candidates=scenario.get("idea_candidates"),
        )
        got = result["answer_type"]
        expected = scenario["expect_answer_type"]
        status = "PASS" if got == expected else "FAIL"
        print(f"[{status}] {scenario['label']}")
        print(f"    답변: {scenario['user_answer']!r}")
        print(f"    기대={expected} 실제={got} 이유={result['reason']}")
        if got == "clarification_request":
            print(f"    설명 응답: {result['clarification_response']}")
        elif got == "insufficient_answer":
            print(f"    재질문: {result['follow_up_question']}")
        if got != expected:
            failures.append(scenario["label"])

    return failures


def check_clarification_then_answer_flow() -> bool:
    """설명 요청 -> 재질문 카운터 미증가 -> 실제 답변 -> 재질문 없이 다음 단계 진행을 실제
    대화(start_ideation_conversation + reply_ideation_conversation)로 끝까지 확인한다."""
    from graph import reply_ideation_conversation, start_ideation_conversation

    llm_call = make_llm_call()
    notice_and_criteria = {
        "competition_name": "1인 가구 생활 안전·생활비 지원 공모전",
        "notice_document": "1인 가구를 위한 생활비 절감 또는 안전 향상 서비스를 우대한다.",
    }
    state = start_ideation_conversation(
        session_id="SUFFICIENCY-MANUAL",
        notice_and_criteria=notice_and_criteria,
        user_idea={"description": "1인 가구를 위한 생활비 절감과 안전 확인을 결합한 서비스"},
        llm_call=llm_call,
    )
    if state["phase"] != "awaiting_planning_answer":
        print(f"시작 직후 phase가 예상과 다릅니다: {state['phase']}", file=sys.stderr)
        return False
    original_pending_question = state["pending_question"]
    print(f"\n기획 전문가 첫 질문: {original_pending_question}")

    state = reply_ideation_conversation(
        previous_state=state, user_message="가치의 종류에는 무엇이 있나요?", llm_call=llm_call
    )
    print(f"설명 요청에 대한 응답: {state['messages'][-1]['content']}")
    if state["phase"] != "awaiting_planning_answer":
        print("설명 요청 후 phase가 바뀌었습니다(같은 질문을 계속 기다려야 합니다).", file=sys.stderr)
        return False
    if state["answer_retry_count"] != 0:
        print(f"설명 요청이 answer_retry_count를 증가시켰습니다: {state['answer_retry_count']}", file=sys.stderr)
        return False
    if state["pending_question"] != original_pending_question:
        print("설명 요청 후 원래 질문이 바뀌었습니다.", file=sys.stderr)
        return False

    state = reply_ideation_conversation(previous_state=state, user_message="생활비 절감이 중요합니다", llm_call=llm_call)
    print(f"실제 답변 후 phase: {state['phase']}")
    if state["phase"] != "awaiting_developer_answer":
        print("설명 후 실제로 답했는데도 다음 단계(개발 전문가 질문)로 진행하지 못했습니다.", file=sys.stderr)
        return False

    print("실제 대화 흐름 확인 통과 — 설명 요청은 재질문 없이 처리되고, 이후 답변은 정상 진행됩니다.")
    return True


def main() -> int:
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY 환경변수가 설정되어 있지 않습니다.", file=sys.stderr)
        return 1

    llm_call = make_llm_call()

    print("=== 1단계: 단위 시나리오 ===")
    failures = run_unit_scenarios(llm_call)
    print()
    if failures:
        print(f"회귀 발견 — {len(failures)}개 시나리오가 기대와 다르게 판정됨: {failures}", file=sys.stderr)
        return 2
    print("모든 단위 시나리오가 기대한 판정과 일치했습니다.")

    print("\n=== 2단계: 실제 대화 흐름 확인 ===")
    if not check_clarification_then_answer_flow():
        return 3

    return 0


if __name__ == "__main__":
    sys.exit(main())
