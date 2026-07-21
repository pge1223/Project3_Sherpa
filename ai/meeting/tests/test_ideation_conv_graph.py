# 작성자: 용준/Claude(2026-07-20)
# 목적: 대화형 아이디어 발전 회의(ideation-conversation) 그래프 검증 — 기획 질문 직후/
#       개발 질문 직후 각각 정지하는지, 개발 전문가가 사용자 답변 전에는 절대 실행되지
#       않는지, max_rounds가 강제되는지, 라운드 계속 시 다음 질문까지 자동 생성되는지,
#       확정은 오직 finalize_ideation_conversation() 호출로만 일어나는지를 실제 LLM
#       호출 없이 확인한다. 기존 test_ideation_graph.py(배치형)와 같은 stub 패턴을 쓴다.
# import: 표준 라이브러리 json/sys/pathlib, pytest; ai/meeting/graph 패키지.

import json
import re
import sys
from pathlib import Path

import pytest

MEETING_DIR = Path(__file__).resolve().parents[1]  # ai/meeting
sys.path.insert(0, str(MEETING_DIR))

from graph import (  # noqa: E402
    finalize_ideation_conversation,
    reply_ideation_conversation,
    start_ideation_conversation,
)

NOTICE_AND_CRITERIA = {
    "competition_name": "지역 소상공인 디지털전환 공모전",
    "notice_document": "실현가능성, 차별성을 평가한다.",
}
USER_IDEA = {"description": "소상공인이 손님 문의에 자동으로 답하는 챗봇"}

_REMAINING_TOPICS_RE = re.compile(
    r"\[아직 확인되지 않은 주제\(우선순위 순\) remaining_topics\]\n(.*?)\n\n", re.S
)


def _topic_from_prompt(prompt: str) -> str:
    """질문 프롬프트에 실제로 주입된 remaining_topics(우선순위 순, 이미 resolved_topics를
    반영해 필터링된 값)의 맨 앞 항목을 그대로 골라 쓴다 — stub이 실제 코드가 계산한 값과
    항상 일치하는 question_topic을 반환하도록 보장하기 위함이다(고정된 topic을 하드코딩하면
    두 번째 질문 호출부터 "이미 해결된 주제" 검증에 걸릴 수 있다)."""
    match = _REMAINING_TOPICS_RE.search(prompt)
    if not match:
        return "problem"
    try:
        remaining = json.loads(match.group(1))
    except (ValueError, TypeError):
        return "problem"
    return remaining[0] if remaining else "problem"


class ScriptedLLM:
    """프롬프트 내용을 보고 어느 노드가 호출했는지 판별해 고정 응답을 돌려주는 stub.

    sufficiency_queue: "[판정 규칙]"(answer_sufficiency 판정 프롬프트) 호출마다 순서대로
    꺼내 쓰는 응답 목록. 비어 있으면 항상 충분(is_sufficient=true)으로 응답한다 — 기존
    라운드 진행 테스트가 재질문 게이트 때문에 깨지지 않도록 하는 기본값이다.
    """

    def __init__(self, dev_next_action="await_user_decision", broken_for=None, sufficiency_queue=None):
        self.captured_prompts: list[str] = []
        self.dev_next_action = dev_next_action
        self.broken_for = broken_for or set()
        self.sufficiency_queue = list(sufficiency_queue) if sufficiency_queue else []

    def __call__(self, prompt: str) -> str:
        self.captured_prompts.append(prompt)

        is_planning = "당신은 AI Review Board의 기획 전문가입니다" in prompt
        is_dev = "당신은 AI Review Board의 개발 전문가입니다" in prompt

        if '"idea_name"' in prompt:
            return json.dumps(
                {
                    "idea_name": "동네 가게 챗봇",
                    "one_line_pitch": "소상공인 손님 문의 자동 응대",
                    "problem_definition": "반복 문의 응대 부담",
                    "target_user": "동네 소상공인",
                    "core_user_value": "문의 응대 시간 절감",
                    "key_features": ["자주 묻는 질문 자동 응답"],
                    "required_data": ["자주 묻는 질문 목록"],
                    "tech_direction": "카카오톡 챗봇빌더",
                    "mvp_scope": ["FAQ 자동 응답"],
                    "differentiation": "저비용 구축",
                    "risks_and_mitigations": [{"risk": "오답 응대", "mitigation": "FAQ 범위 밖 질문은 사람에게 이관"}],
                    "success_metrics": ["자동 응답률"],
                    "expert_final_opinions": {"planning_expert": "적합", "dev_expert": "구현 가능"},
                    "unverified_assumptions": [],
                    "final_recommendation": "추천",
                    "final_recommendation_reason": "MVP로 검증 가능",
                    "next_actions": ["FAQ 정리"],
                },
                ensure_ascii=False,
            )

        if "[판정 규칙]" in prompt:
            if "sufficiency" in self.broken_for:
                return "이것은 JSON이 아닙니다"
            if self.sufficiency_queue:
                return json.dumps(self.sufficiency_queue.pop(0), ensure_ascii=False)
            return json.dumps(
                {"is_sufficient": True, "reason": "핵심 질문에 구체적으로 답했습니다", "follow_up_question": None},
                ensure_ascii=False,
            )

        if "[질문 규칙]" in prompt:
            if is_planning and "planning_question" in self.broken_for:
                return "이것은 JSON이 아닙니다"
            if is_dev and "developer_question" in self.broken_for:
                return "이것은 JSON이 아닙니다"
            speaker = "planning_expert" if is_planning else "dev_expert"
            return json.dumps(
                {
                    "judgment": f"[{speaker}] 현재까지 확인된 내용입니다",
                    "question": f"[{speaker}] 핵심 질문입니다",
                    "question_topic": _topic_from_prompt(prompt),
                    "referenced_message_ids": [],
                    "evidence": [],
                },
                ensure_ascii=False,
            )

        if "[의견 규칙]" in prompt:
            next_action = self.dev_next_action if is_dev else None
            speaker = "dev" if is_dev else "planning"
            return json.dumps(
                {
                    "stance": "보완",
                    "judgment": f"[{speaker}] 핵심 판단입니다",
                    "reason": f"[{speaker}] 판단 근거입니다",
                    "suggestion": f"[{speaker}] 개선 제안입니다",
                    "confirmed": ["소상공인 손님 응대 자동화로 범위를 좁힌다"],
                    "unconfirmed": ["결제 연동 필요 여부"],
                    "referenced_message_ids": [],
                    "evidence": [],
                    "next_action": next_action,
                },
                ensure_ascii=False,
            )

        raise AssertionError(f"예상하지 못한 프롬프트입니다: {prompt[:200]}")


def _start(llm, max_rounds=3):
    return start_ideation_conversation(
        session_id="CONV-TEST",
        notice_and_criteria=NOTICE_AND_CRITERIA,
        user_idea=USER_IDEA,
        llm_call=llm,
        max_rounds=max_rounds,
    )


# ---------------------------------------------------------------------------
# 1. 세션을 시작하면 기획 전문가의 질문 하나만 만들고 즉시 멈추는지
# ---------------------------------------------------------------------------


def test_start_stops_after_single_planning_question():
    llm = ScriptedLLM()
    state = _start(llm)
    assert state["phase"] == "awaiting_planning_answer"
    assert len(state["messages"]) == 1
    assert state["messages"][0]["speaker_id"] == "planning_expert"
    assert state["messages"][0]["message_type"] == "question"
    dev_prompts = [p for p in llm.captured_prompts if "당신은 AI Review Board의 개발 전문가입니다" in p]
    assert not dev_prompts, "사용자가 답하기 전에 개발 전문가가 호출되면 안 된다"


# ---------------------------------------------------------------------------
# 2. 사용자가 기획 질문에 답하면 개발 전문가가 그 답변을 참조해 질문 하나만 만들고 멈추는지
# ---------------------------------------------------------------------------


def test_reply_to_planning_question_triggers_only_developer_question():
    llm = ScriptedLLM()
    state = _start(llm)
    state = reply_ideation_conversation(previous_state=state, user_message="타깃은 동네 카페 사장님입니다", llm_call=llm)

    assert state["phase"] == "awaiting_developer_answer"
    assert state["messages"][-2]["speaker_id"] == "user"
    assert state["messages"][-2]["content"] == "타깃은 동네 카페 사장님입니다"
    assert state["messages"][-1]["speaker_id"] == "dev_expert"
    assert state["messages"][-1]["message_type"] == "question"

    dev_prompt = next(p for p in llm.captured_prompts if "당신은 AI Review Board의 개발 전문가입니다" in p)
    assert "타깃은 동네 카페 사장님입니다" in dev_prompt


# ---------------------------------------------------------------------------
# 3. 사용자가 개발 질문에 답하면 두 전문가가 순서대로 보완 의견을 말하는지
# ---------------------------------------------------------------------------


def test_reply_to_developer_question_runs_both_experts_in_order():
    llm = ScriptedLLM(dev_next_action="await_user_decision")
    state = _start(llm)
    state = reply_ideation_conversation(previous_state=state, user_message="답변1", llm_call=llm)
    state = reply_ideation_conversation(previous_state=state, user_message="카카오톡 채널 API를 쓰려 합니다", llm_call=llm)

    assert state["phase"] == "awaiting_user_decision"
    speakers = [m["speaker_id"] for m in state["messages"]]
    # user(답1), user(답2) 다음에 planning_expert -> dev_expert 순서로 이어져야 한다.
    assert speakers[-2:] == ["planning_expert", "dev_expert"]
    assert state["messages"][-2]["message_type"] == "opinion"
    assert state["messages"][-1]["message_type"] == "opinion"
    assert "결제 연동 필요 여부" in state["unresolved_issues"]


# ---------------------------------------------------------------------------
# 4. 개발 전문가가 continue_round를 판단하면 같은 호출 안에서 다음 질문까지 자동 생성되는지
# ---------------------------------------------------------------------------


def test_continue_round_auto_generates_next_planning_question():
    llm = ScriptedLLM(dev_next_action="continue_round")
    state = _start(llm, max_rounds=3)
    state = reply_ideation_conversation(previous_state=state, user_message="답변1", llm_call=llm)
    state = reply_ideation_conversation(previous_state=state, user_message="답변2", llm_call=llm)

    assert state["phase"] == "awaiting_planning_answer"
    assert state["round"] == 2
    assert state["messages"][-1]["speaker_id"] == "planning_expert"
    assert state["messages"][-1]["message_type"] == "question"


# ---------------------------------------------------------------------------
# 5. max_rounds에 도달하면 LLM이 continue_round를 반환해도 강제로 사용자 대기로 가는지
# ---------------------------------------------------------------------------


def test_max_rounds_forces_awaiting_user_decision_even_if_llm_says_continue():
    llm = ScriptedLLM(dev_next_action="continue_round")
    state = _start(llm, max_rounds=1)
    state = reply_ideation_conversation(previous_state=state, user_message="답변1", llm_call=llm)
    state = reply_ideation_conversation(previous_state=state, user_message="답변2", llm_call=llm)

    assert state["phase"] == "awaiting_user_decision"
    assert state["round"] == 1


# ---------------------------------------------------------------------------
# 6. 사용자가 확정하기 전에는 idea_proposal이 생기지 않는지 + finalize를 불러야만 생기는지
# ---------------------------------------------------------------------------


def test_idea_proposal_only_exists_after_explicit_finalize_call():
    llm = ScriptedLLM(dev_next_action="await_user_decision")
    state = _start(llm)
    state = reply_ideation_conversation(previous_state=state, user_message="답변1", llm_call=llm)
    state = reply_ideation_conversation(previous_state=state, user_message="답변2", llm_call=llm)
    assert state["idea_proposal"] is None
    assert not any('"idea_name"' in p for p in llm.captured_prompts)

    state = finalize_ideation_conversation(previous_state=state, llm_call=llm)
    assert state["phase"] == "finalized"
    assert state["idea_proposal"]["idea_name"] == "동네 가게 챗봇"


# ---------------------------------------------------------------------------
# 7. awaiting_user_decision이 아닌 상태에서 finalize를 부르면 거부되는지
# ---------------------------------------------------------------------------


def test_finalize_rejected_before_awaiting_user_decision():
    llm = ScriptedLLM()
    state = _start(llm)
    with pytest.raises(ValueError):
        finalize_ideation_conversation(previous_state=state, llm_call=llm)


# ---------------------------------------------------------------------------
# 8. 잘못된 phase(finalized/failed)에서 reply를 부르면 거부되는지
# ---------------------------------------------------------------------------


def test_reply_rejected_when_conversation_already_finalized():
    llm = ScriptedLLM(dev_next_action="await_user_decision")
    state = _start(llm)
    state = reply_ideation_conversation(previous_state=state, user_message="답변1", llm_call=llm)
    state = reply_ideation_conversation(previous_state=state, user_message="답변2", llm_call=llm)
    state = finalize_ideation_conversation(previous_state=state, llm_call=llm)

    with pytest.raises(ValueError):
        reply_ideation_conversation(previous_state=state, user_message="더 할 말 있어요", llm_call=llm)


# ---------------------------------------------------------------------------
# 9. JSON 파싱 실패 시 폴백이 동작하는지(질문 턴)
# ---------------------------------------------------------------------------


def test_json_parse_failure_falls_back_to_failed_phase():
    llm = ScriptedLLM(broken_for={"planning_question"})
    state = _start(llm)
    assert state["phase"] == "failed"
    assert state["failed_node"] == "question__planning_expert"


# ---------------------------------------------------------------------------
# 10. 기획/개발 두 전문가가 서로 다른 역할 지시를 받는지(프롬프트 경계)
# ---------------------------------------------------------------------------


def test_planning_and_dev_prompts_carry_different_role_instructions():
    llm = ScriptedLLM(dev_next_action="await_user_decision")
    state = _start(llm)
    state = reply_ideation_conversation(previous_state=state, user_message="답변1", llm_call=llm)
    reply_ideation_conversation(previous_state=state, user_message="답변2", llm_call=llm)

    planning_prompts = [p for p in llm.captured_prompts if "당신은 AI Review Board의 기획 전문가입니다" in p]
    dev_prompts = [p for p in llm.captured_prompts if "당신은 AI Review Board의 개발 전문가입니다" in p]
    assert planning_prompts and dev_prompts
    assert all("당신은 AI Review Board의 개발 전문가입니다" not in p for p in planning_prompts)
    assert all("당신은 AI Review Board의 기획 전문가입니다" not in p for p in dev_prompts)


# ---------------------------------------------------------------------------
# 11. 답변이 불충분하면 다음 전문가로 넘어가지 않고 재질문이 생성되는지(요청 3번)
# ---------------------------------------------------------------------------


def test_insufficient_answer_triggers_follow_up_instead_of_next_question():
    llm = ScriptedLLM(
        sufficiency_queue=[
            {"is_sufficient": False, "reason": "구체성이 부족합니다", "follow_up_question": "정확히 누구를 위한 서비스인가요?"}
        ]
    )
    state = _start(llm)
    state = reply_ideation_conversation(previous_state=state, user_message="그런 것 같아요", llm_call=llm)

    # 재질문 후에도 여전히 기획 질문 답변을 기다리는 상태여야 하고, 개발 전문가는 아직 호출되면 안 된다.
    assert state["phase"] == "awaiting_planning_answer"
    assert state["answer_retry_count"] == 1
    assert state["messages"][-1]["speaker_id"] == "planning_expert"
    assert state["messages"][-1]["message_type"] == "question"
    assert "정확히 누구를 위한 서비스인가요?" in state["messages"][-1]["content"]
    dev_prompts = [p for p in llm.captured_prompts if "당신은 AI Review Board의 개발 전문가입니다" in p]
    assert not dev_prompts, "재질문 상황에서는 개발 전문가가 호출되면 안 된다"


# ---------------------------------------------------------------------------
# 12. 같은 쟁점의 재질문이 상한(2회)에 도달하면 판정과 무관하게 다음 단계로 강제 진행되는지(요청 5번)
# ---------------------------------------------------------------------------


def test_repeated_insufficient_answers_force_progress_after_retry_cap():
    llm = ScriptedLLM(
        sufficiency_queue=[
            {"is_sufficient": False, "reason": "여전히 모호합니다", "follow_up_question": "다시 설명해 주세요"},
            {"is_sufficient": False, "reason": "여전히 모호합니다", "follow_up_question": "다시 설명해 주세요"},
            {"is_sufficient": False, "reason": "세 번째도 불충분합니다", "follow_up_question": "다시 설명해 주세요"},
        ]
    )
    state = _start(llm)
    state = reply_ideation_conversation(previous_state=state, user_message="그런 것 같아요", llm_call=llm)
    assert state["phase"] == "awaiting_planning_answer"
    assert state["answer_retry_count"] == 1

    state = reply_ideation_conversation(previous_state=state, user_message="음... 아마도요", llm_call=llm)
    assert state["phase"] == "awaiting_planning_answer"
    assert state["answer_retry_count"] == 2

    # 세 번째 판정도 불충분이지만 retry_count(2)가 상한에 도달했으므로 강제로 다음 단계(개발 전문가
    # 질문)로 넘어가야 한다.
    state = reply_ideation_conversation(previous_state=state, user_message="여전히 애매해요", llm_call=llm)
    assert state["phase"] == "awaiting_developer_answer"
    assert state["answer_retry_count"] == 0
    assert any("불명확하여 다음 가정으로 진행합니다" in issue for issue in state["unresolved_issues"])


# ---------------------------------------------------------------------------
# 13. 충분한 답변은 재질문 없이 곧바로 다음 단계로 진행되는지 + 전문가 의견이 구조화된 형식으로 출력되는지(요청 4번)
# ---------------------------------------------------------------------------


def test_sufficient_answer_advances_and_opinion_is_structured():
    llm = ScriptedLLM(dev_next_action="await_user_decision")
    state = _start(llm)
    state = reply_ideation_conversation(previous_state=state, user_message="타깃은 동네 카페 사장님입니다", llm_call=llm)
    assert state["phase"] == "awaiting_developer_answer"
    assert state["answer_retry_count"] == 0

    state = reply_ideation_conversation(previous_state=state, user_message="카카오톡 채널 API를 쓰려 합니다", llm_call=llm)
    assert state["phase"] == "awaiting_user_decision"

    planning_opinion = next(m for m in state["messages"] if m["speaker_id"] == "planning_expert" and m["message_type"] == "opinion")
    for header in ("[판단]", "[근거]", "[제안]", "[확정 사항]", "[미확정 사항]"):
        assert header in planning_opinion["content"]


# ---------------------------------------------------------------------------
# 14. answer_retry_count가 전역 누적이 아니라 "현재 쟁점"에만 스코프되는지(리뷰 지적 1번)
# ---------------------------------------------------------------------------


def test_retry_count_is_scoped_to_current_pending_question_not_global():
    llm = ScriptedLLM(
        sufficiency_queue=[
            {"is_sufficient": False, "reason": "불명확(기획1)", "follow_up_question": "다시 설명해주세요(기획)"},
            {"is_sufficient": False, "reason": "불명확(기획2)", "follow_up_question": "다시 설명해주세요(기획)"},
            # retry_count가 상한(2)에 도달한 뒤의 세 번째 판정 — 결과와 무관하게 강제 진행되므로
            # is_sufficient=false를 반환해도 다음 단계로 넘어가야 한다.
            {"is_sufficient": False, "reason": "세 번째도 불명확", "follow_up_question": None},
            {"is_sufficient": False, "reason": "불명확(개발1)", "follow_up_question": "다시 설명해주세요(개발)"},
        ]
    )
    state = _start(llm)

    state = reply_ideation_conversation(previous_state=state, user_message="모호1", llm_call=llm)
    assert state["phase"] == "awaiting_planning_answer"
    assert state["answer_retry_count"] == 1

    state = reply_ideation_conversation(previous_state=state, user_message="모호2", llm_call=llm)
    assert state["phase"] == "awaiting_planning_answer"
    assert state["answer_retry_count"] == 2

    # 상한 도달 -> 판정 결과와 무관하게 개발 전문가 질문으로 강제 진행 + 카운터 리셋.
    state = reply_ideation_conversation(previous_state=state, user_message="모호3", llm_call=llm)
    assert state["phase"] == "awaiting_developer_answer"
    assert state["answer_retry_count"] == 0

    # 새 쟁점(개발 전문가 질문)의 첫 모호한 답변 — 기획 쟁점에서 쌓인 누적치(2)를 이어받지
    # 않고 1부터 다시 시작해야 한다(전역 카운터가 아니라 쟁점별 카운터임을 검증).
    state = reply_ideation_conversation(previous_state=state, user_message="모호(개발)", llm_call=llm)
    assert state["phase"] == "awaiting_developer_answer"
    assert state["answer_retry_count"] == 1


# ---------------------------------------------------------------------------
# expected_answer_type 플러밍 — 실제 모델의 판정 품질(생활비 절감 답변이 부당하게
# 재질문당한 문제)은 scripts/run_ideation_sufficiency_scenarios.py(실제 LLM)로 확인한다.
# 여기서는 stub으로 "질문 노드가 만든 expected_answer_type이 state에 저장되고, sufficiency
# 프롬프트에 실제로 전달되는지"라는 배선(plumbing)만 결정적으로 검증한다.
# ---------------------------------------------------------------------------


def _llm_with_question_expected_answer_type(expected_answer_type):
    """planning_question 노드가 주어진 expected_answer_type을 반환하고, 그 외(sufficiency
    포함)는 항상 충분 판정을 내리는 최소 stub."""
    captured_sufficiency_prompts: list[str] = []

    def llm_call(prompt: str) -> str:
        if "[질문 규칙]" in prompt:
            return json.dumps(
                {
                    "judgment": "현재까지 확인된 내용입니다",
                    "question": "핵심 질문입니다",
                    "question_topic": _topic_from_prompt(prompt),
                    "expected_answer_type": expected_answer_type,
                    "referenced_message_ids": [],
                    "evidence": [],
                },
                ensure_ascii=False,
            )
        if "[판정 규칙]" in prompt:
            captured_sufficiency_prompts.append(prompt)
            return json.dumps(
                {"is_sufficient": True, "reason": "충분", "follow_up_question": None}, ensure_ascii=False
            )
        raise AssertionError(f"예상하지 못한 프롬프트입니다: {prompt[:200]}")

    llm_call.captured_sufficiency_prompts = captured_sufficiency_prompts
    return llm_call


def test_question_node_stores_expected_answer_type_in_state():
    llm = _llm_with_question_expected_answer_type("preference")
    state = _start(llm)
    assert state["pending_expected_answer_type"] == "preference"


def test_expected_answer_type_is_forwarded_to_sufficiency_prompt():
    llm = _llm_with_question_expected_answer_type("selection")
    state = _start(llm)
    reply_ideation_conversation(previous_state=state, user_message="1번이 더 좋다", llm_call=llm)

    assert llm.captured_sufficiency_prompts
    assert "[expected_answer_type]\nselection" in llm.captured_sufficiency_prompts[-1]


def test_invalid_expected_answer_type_falls_back_to_unknown_in_sufficiency_prompt():
    """LLM이 허용값 밖의 값(스키마 오류)을 반환해도 질문 생성 자체는 실패시키지 않고,
    sufficiency 프롬프트에는 "미상"으로 전달돼야 한다(요청 사항의 하위 호환 원칙)."""
    llm = _llm_with_question_expected_answer_type("이상한값")
    state = _start(llm)
    assert state["pending_expected_answer_type"] is None

    reply_ideation_conversation(previous_state=state, user_message="답변", llm_call=llm)
    assert "[expected_answer_type]\n미상(알 수 없음)" in llm.captured_sufficiency_prompts[-1]


def test_pending_expected_answer_type_resets_after_advancing_to_next_question():
    """기획 질문은 expected_answer_type="preference"를 만들지만, 개발 질문은 이 키 자체를
    주지 않는다(구버전 응답을 흉내) — 이전 질문의 값이 다음 질문으로 새어 나오지 않고
    None으로 정확히 리셋되는지 확인한다."""
    question_call_count = {"n": 0}

    def llm_call(prompt: str) -> str:
        if "[질문 규칙]" in prompt:
            question_call_count["n"] += 1
            payload = {
                "judgment": "현재까지 확인된 내용입니다",
                "question": "핵심 질문입니다",
                "question_topic": _topic_from_prompt(prompt),
                "referenced_message_ids": [],
                "evidence": [],
            }
            if question_call_count["n"] == 1:
                payload["expected_answer_type"] = "preference"
            return json.dumps(payload, ensure_ascii=False)
        if "[판정 규칙]" in prompt:
            return json.dumps(
                {"is_sufficient": True, "reason": "충분", "follow_up_question": None}, ensure_ascii=False
            )
        raise AssertionError(f"예상하지 못한 프롬프트입니다: {prompt[:200]}")

    state = _start(llm_call)
    assert state["pending_expected_answer_type"] == "preference"

    state = reply_ideation_conversation(previous_state=state, user_message="1번이 더 좋다", llm_call=llm_call)
    assert state["phase"] == "awaiting_developer_answer"
    assert state.get("pending_expected_answer_type") is None


# ---------------------------------------------------------------------------
# clarification_request — "가치의 종류에는 무엇이 있나요?" 같은 용어/예시/선택지 설명
# 요청을 불충분한 답변으로 오판해 같은 질문을 반복하지 않는지 검증한다(실제 대화에서
# 확인된 문제). 여기서는 stub으로 "answer_type이 clarification_request일 때 배선이
# 정확히 동작하는지"(재질문 카운터 미증가, pending_question 유지, 설명 메시지 추가)만
# 결정적으로 검증한다 — 실제 모델이 이 세 메시지를 clarification_request로 올바르게
# *분류*하는지는 scripts/run_ideation_sufficiency_scenarios.py(실제 LLM)로 확인한다.
# ---------------------------------------------------------------------------


def _llm_with_sufficiency_response(sufficiency_response: dict):
    """[질문 규칙] 호출에는 고정 질문을, [판정 규칙] 호출에는 주어진 sufficiency_response를
    그대로 반환하는 최소 stub. captured_prompts로 호출 여부(특히 개발 전문가 호출 여부)를
    검사할 수 있다."""
    captured_prompts: list[str] = []

    def llm_call(prompt: str) -> str:
        captured_prompts.append(prompt)
        if "[질문 규칙]" in prompt:
            return json.dumps(
                {
                    "judgment": "현재까지 확인된 내용입니다",
                    "question": "핵심 질문입니다",
                    "question_topic": _topic_from_prompt(prompt),
                    "expected_answer_type": "preference",
                    "referenced_message_ids": [],
                    "evidence": [],
                },
                ensure_ascii=False,
            )
        if "[판정 규칙]" in prompt:
            return json.dumps(sufficiency_response, ensure_ascii=False)
        raise AssertionError(f"예상하지 못한 프롬프트입니다: {prompt[:200]}")

    llm_call.captured_prompts = captured_prompts
    return llm_call


@pytest.mark.parametrize("clarification_message", ["가치의 종류에는 무엇이 있나요?", "예시를 들어주세요", "질문이 무슨 뜻인가요?"])
def test_clarification_request_message_types_are_handled_without_reasking_raw(clarification_message):
    """세 표현 모두(LLM이 clarification_request로 분류했다고 가정) 재질문 카운터를 늘리지
    않고, 설명 메시지를 추가하며, 원래 pending_question을 그대로 유지해야 한다."""
    llm = _llm_with_sufficiency_response(
        {
            "answer_type": "clarification_request",
            "reason": "사용자가 설명을 요청했습니다",
            "follow_up_question": None,
            "clarification_response": (
                "선택 가능한 핵심 가치에는 생활비 절감, 안전 향상, 편의성, 맞춤형 정보 제공, "
                "정보 접근성 등이 있습니다. 현재 두 후보를 고려하면 생활비 절감과 안전 향상이 "
                "주요 선택지입니다. 둘 중 MVP에서 가장 우선할 가치 하나를 선택해 주세요."
            ),
        }
    )
    state = _start(llm)
    original_pending_question = state["pending_question"]

    state = reply_ideation_conversation(previous_state=state, user_message=clarification_message, llm_call=llm)

    assert state["phase"] == "awaiting_planning_answer"  # 같은 질문을 여전히 기다린다.
    assert state["pending_question"] == original_pending_question  # 원래 질문이 유지된다.
    assert state["answer_retry_count"] == 0  # 요청: 설명 요청은 재질문 카운터를 늘리지 않는다.
    assert state["messages"][-1]["speaker_id"] == "planning_expert"
    assert "생활비 절감" in state["messages"][-1]["content"]
    assert "[설명]" in state["messages"][-1]["content"]
    dev_prompts = [p for p in llm.captured_prompts if "당신은 AI Review Board의 개발 전문가입니다" in p]
    assert not dev_prompts, "설명 요청 상황에서는 개발 전문가가 호출되면 안 된다"


def test_clarification_request_then_sufficient_answer_advances_normally():
    """설명을 들은 뒤 사용자가 실제로 답하면(다음 reply 호출에서 answer_type="answer")
    정상적으로 다음 단계(개발 전문가 질문)까지 진행돼야 한다 — 요청: 설명 후 선택 질문
    하나만 다시 제시하고, 그 질문에 답하면 정상 진행."""
    responses = [
        {
            "answer_type": "clarification_request",
            "reason": "설명 요청",
            "follow_up_question": None,
            "clarification_response": "선택지는 생활비 절감과 안전 향상입니다. 어느 쪽을 우선하시겠어요?",
        },
        {"answer_type": "answer", "reason": "충분", "follow_up_question": None, "clarification_response": None},
    ]

    def llm_call(prompt: str) -> str:
        if "[질문 규칙]" in prompt:
            return json.dumps(
                {
                    "judgment": "현재까지 확인된 내용입니다",
                    "question": "핵심 질문입니다",
                    "question_topic": _topic_from_prompt(prompt),
                    "expected_answer_type": "preference",
                    "referenced_message_ids": [],
                    "evidence": [],
                },
                ensure_ascii=False,
            )
        if "[판정 규칙]" in prompt:
            return json.dumps(responses.pop(0), ensure_ascii=False)
        raise AssertionError(f"예상하지 못한 프롬프트입니다: {prompt[:200]}")

    state = _start(llm_call)
    state = reply_ideation_conversation(previous_state=state, user_message="가치의 종류가 뭔가요?", llm_call=llm_call)
    assert state["phase"] == "awaiting_planning_answer"
    assert state["answer_retry_count"] == 0

    state = reply_ideation_conversation(previous_state=state, user_message="생활비 절감이 중요합니다", llm_call=llm_call)
    assert state["phase"] == "awaiting_developer_answer"  # 설명 후 정상적으로 다음 단계로 진행.


def test_answer_type_answer_advances_without_retry():
    llm = _llm_with_sufficiency_response(
        {"answer_type": "answer", "reason": "명확히 선택함", "follow_up_question": None, "clarification_response": None}
    )
    state = _start(llm)
    state = reply_ideation_conversation(previous_state=state, user_message="생활비 절감이 중요합니다", llm_call=llm)
    assert state["phase"] == "awaiting_developer_answer"
    assert state["answer_retry_count"] == 0


def test_answer_type_insufficient_answer_triggers_follow_up_and_increments_retry():
    llm = _llm_with_sufficiency_response(
        {
            "answer_type": "insufficient_answer",
            "reason": "우선순위를 정하지 않았습니다",
            "follow_up_question": "둘 중 무엇을 더 우선하시겠어요?",
            "clarification_response": None,
        }
    )
    state = _start(llm)
    state = reply_ideation_conversation(previous_state=state, user_message="잘 모르겠습니다", llm_call=llm)
    assert state["phase"] == "awaiting_planning_answer"
    assert state["answer_retry_count"] == 1
    assert "둘 중 무엇을 더 우선하시겠어요?" in state["messages"][-1]["content"]


# ---------------------------------------------------------------------------
# 15. answer_retry_count 필드가 없는 구버전 저장 state를 재개해도 KeyError 없이 동작하는지
#     (리뷰 지적 2번 — 배포 전에 저장된 세션을 재개하는 상황을 흉내낸다)
# ---------------------------------------------------------------------------


def test_reply_works_when_previous_state_missing_answer_retry_count_field():
    llm = ScriptedLLM()
    state = _start(llm)
    legacy_state = dict(state)
    del legacy_state["answer_retry_count"]

    new_state = reply_ideation_conversation(
        previous_state=legacy_state, user_message="타깃은 동네 카페 사장님입니다", llm_call=llm
    )
    assert new_state["phase"] == "awaiting_developer_answer"
    assert new_state["answer_retry_count"] == 0


# ---------------------------------------------------------------------------
# 16. 구조화 응답이 깨졌을 때(리뷰 지적 4번): 필수 키 누락 / 배열 대신 문자열 / 빈 응답 /
#     JSON 앞뒤 설명문 / sufficiency 호출 실패
# ---------------------------------------------------------------------------


def test_question_node_rejects_missing_keys_instead_of_producing_empty_card():
    """judgment/question 키가 아예 없는 응답 — 빈 카드를 만들지 않고(요청 7번) 재시도 1회
    후에도 여전히 비어 있으면 phase="failed"로 안전하게 끝난다. 이전 실사용에서 빈 카드가
    화면에 보였던 문제(요청 7번 배경)를 재현하지 않는지 검증한다."""

    call_count = {"n": 0}

    def llm(prompt: str) -> str:
        if "[질문 규칙]" in prompt:
            call_count["n"] += 1
            return json.dumps({"referenced_message_ids": [], "evidence": []}, ensure_ascii=False)
        raise AssertionError(f"예상하지 못한 프롬프트: {prompt[:100]}")

    state = start_ideation_conversation(
        session_id="CONV-TEST-MISSING-KEYS",
        notice_and_criteria=NOTICE_AND_CRITERIA,
        user_idea=USER_IDEA,
        llm_call=llm,
    )
    assert state["phase"] == "failed"
    assert state["failed_node"] == "question__planning_expert"
    assert state["messages"] == []  # 빈 content의 메시지가 저장되지 않았다.
    assert state["pending_question"] is None  # 빈 pending_question이 저장되지 않았다.
    assert call_count["n"] == 2  # 최초 1회 + 재시도 1회, 총 2회 시도했다.


def test_discussion_node_handles_non_list_confirmed_and_unconfirmed_safely():
    """confirmed/unconfirmed가 배열이 아니라 문자열로 오면(타입 오류) consensus/unresolved_issues가
    그 문자열의 글자 단위로 쪼개져 오염되면 안 된다."""

    def llm(prompt: str) -> str:
        if "[판정 규칙]" in prompt:
            return json.dumps({"is_sufficient": True, "reason": "충분", "follow_up_question": None}, ensure_ascii=False)
        if "[질문 규칙]" in prompt:
            is_planning = "당신은 AI Review Board의 기획 전문가입니다" in prompt
            speaker = "planning_expert" if is_planning else "dev_expert"
            return json.dumps(
                {
                    "judgment": "판단",
                    "question": f"[{speaker}] 질문",
                    "question_topic": _topic_from_prompt(prompt),
                    "referenced_message_ids": [],
                    "evidence": [],
                },
                ensure_ascii=False,
            )
        if "[의견 규칙]" in prompt:
            is_dev = "당신은 AI Review Board의 개발 전문가입니다" in prompt
            return json.dumps(
                {
                    "stance": "보완",
                    "judgment": "판단",
                    "reason": "근거",
                    "suggestion": "제안",
                    "confirmed": "이것은 배열이 아니라 문자열입니다",
                    "unconfirmed": "이것도 배열이 아니라 문자열입니다",
                    "referenced_message_ids": [],
                    "evidence": [],
                    "next_action": "await_user_decision" if is_dev else None,
                },
                ensure_ascii=False,
            )
        raise AssertionError(f"예상하지 못한 프롬프트: {prompt[:100]}")

    state = _start(llm)
    state = reply_ideation_conversation(previous_state=state, user_message="답변1", llm_call=llm)
    state = reply_ideation_conversation(previous_state=state, user_message="답변2", llm_call=llm)

    assert state["phase"] == "awaiting_user_decision"
    assert state["consensus"] == []
    assert state["unresolved_issues"] == []
    for m in state["messages"]:
        if m["message_type"] == "opinion":
            assert "[확정 사항]\n- (없음)" in m["content"]
            assert "[미확정 사항]\n- (없음)" in m["content"]


def test_node_recovers_when_json_is_wrapped_in_explanatory_prose():
    """코드블록 없이 JSON 앞뒤로 설명문이 붙어 있어도(parse_json_response의 방어적 추출로)
    질문 노드가 실패 처리되지 않고 정상적으로 질문을 만든다."""

    def llm(prompt: str) -> str:
        if "[질문 규칙]" in prompt:
            payload = json.dumps(
                {
                    "judgment": "판단",
                    "question": "핵심 질문",
                    "question_topic": "problem",
                    "referenced_message_ids": [],
                    "evidence": [],
                },
                ensure_ascii=False,
            )
            return f"물론이죠! 요청하신 질문은 다음과 같습니다:\n{payload}\n도움이 되었길 바랍니다."
        raise AssertionError(f"예상하지 못한 프롬프트: {prompt[:100]}")

    state = start_ideation_conversation(
        session_id="CONV-TEST-PROSE-JSON",
        notice_and_criteria=NOTICE_AND_CRITERIA,
        user_idea=USER_IDEA,
        llm_call=llm,
    )
    assert state["phase"] == "awaiting_planning_answer"
    assert state["failed_node"] is None
    assert "핵심 질문" in state["messages"][0]["content"]


def test_empty_llm_response_falls_back_to_failed_phase():
    def llm(prompt: str) -> str:
        return ""

    state = start_ideation_conversation(
        session_id="CONV-TEST-EMPTY-RESPONSE",
        notice_and_criteria=NOTICE_AND_CRITERIA,
        user_idea=USER_IDEA,
        llm_call=llm,
    )
    assert state["phase"] == "failed"
    assert state["failed_node"] == "question__planning_expert"


def test_sufficiency_call_failure_fails_open_and_conversation_still_progresses():
    """sufficiency 판정 호출 자체가 파싱 실패하면(인프라 문제) 회의를 막지 않고 충분함으로
    간주해 정상 진행한다(요청: 판정 호출 실패가 핵심 콘텐츠 생성 실패처럼 전체를 막지 않아야 함)."""
    llm = ScriptedLLM(broken_for={"sufficiency"})
    state = _start(llm)
    state = reply_ideation_conversation(previous_state=state, user_message="타깃은 동네 카페 사장님입니다", llm_call=llm)

    assert state["phase"] == "awaiting_developer_answer"
    assert state["failed_node"] is None
    assert state["answer_retry_count"] == 0


def test_discussion_node_rejects_blank_judgment_instead_of_producing_empty_card():
    """judgment/reason이 빈 문자열인 의견 응답 — 빈 카드를 만들지 않고 재시도 후에도
    여전히 비어 있으면 phase="failed"로 끝난다(요청 7번 배경의 재현 방지)."""

    def llm(prompt: str) -> str:
        if "[판정 규칙]" in prompt:
            return json.dumps({"is_sufficient": True, "reason": "충분", "follow_up_question": None}, ensure_ascii=False)
        if "[질문 규칙]" in prompt:
            is_planning = "당신은 AI Review Board의 기획 전문가입니다" in prompt
            speaker = "planning_expert" if is_planning else "dev_expert"
            return json.dumps(
                {
                    "judgment": "판단",
                    "question": f"[{speaker}] 질문",
                    "question_topic": _topic_from_prompt(prompt),
                    "referenced_message_ids": [],
                    "evidence": [],
                },
                ensure_ascii=False,
            )
        if "[의견 규칙]" in prompt:
            is_planning = "당신은 AI Review Board의 기획 전문가입니다" in prompt
            if is_planning:
                # 기획 전문가 응답만 의도적으로 비운다.
                return json.dumps({"stance": "보완", "judgment": "", "reason": "   ", "referenced_message_ids": [], "evidence": []}, ensure_ascii=False)
            return json.dumps(
                {
                    "stance": "보완",
                    "judgment": "판단",
                    "reason": "근거",
                    "suggestion": "제안",
                    "confirmed": [],
                    "unconfirmed": [],
                    "referenced_message_ids": [],
                    "evidence": [],
                    "next_action": "await_user_decision",
                },
                ensure_ascii=False,
            )
        raise AssertionError(f"예상하지 못한 프롬프트: {prompt[:100]}")

    state = _start(llm)
    state = reply_ideation_conversation(previous_state=state, user_message="답변1", llm_call=llm)
    state = reply_ideation_conversation(previous_state=state, user_message="답변2", llm_call=llm)

    assert state["phase"] == "failed"
    assert state["failed_node"] == "discussion__planning_expert"
    # 실패한 기획 전문가 의견 메시지가 저장되지 않았다 — 빈 카드 금지.
    assert not any(m["speaker_id"] == "planning_expert" and m["message_type"] == "opinion" for m in state["messages"])


# ---------------------------------------------------------------------------
# 17. 종합 응답의 13개 항목 + 부가 필드가 노드/상태를 거치며 하나도 누락되지 않는지
#     (리뷰 지적 3번 — make_conv_synthesis_node는 raw JSON을 그대로 idea_proposal에
#     저장하므로, 필드 화이트리스트나 고정 Pydantic 스키마가 중간에 끼어들지 않는지 검증)
# ---------------------------------------------------------------------------

_SYNTHESIS_13_FIELDS = [
    "problem_definition",
    "target_user",
    "core_user_value",
    "key_features",
    "required_data",
    "tech_direction",
    "mvp_scope",
    "differentiation",
    "risks_and_mitigations",
    "success_metrics",
    "expert_final_opinions",
    "unverified_assumptions",
    "final_recommendation",
]


def test_idea_proposal_preserves_all_13_required_fields_verbatim():
    llm = ScriptedLLM(dev_next_action="await_user_decision")
    state = _start(llm)
    state = reply_ideation_conversation(previous_state=state, user_message="답변1", llm_call=llm)
    state = reply_ideation_conversation(previous_state=state, user_message="답변2", llm_call=llm)
    state = finalize_ideation_conversation(previous_state=state, llm_call=llm)

    assert state["phase"] == "finalized"
    proposal = state["idea_proposal"]
    for field in _SYNTHESIS_13_FIELDS:
        assert field in proposal, f"{field} 가 idea_proposal에서 누락되었습니다"
    # ScriptedLLM이 넣어둔 부가 필드(idea_name 등)도 그대로 남아 있어야 한다 — 중간에
    # 화이트리스트/고정 스키마가 필드를 걸러내지 않는다는 증거.
    assert proposal["idea_name"] == "동네 가게 챗봇"
    assert proposal["expert_final_opinions"] == {"planning_expert": "적합", "dev_expert": "구현 가능"}
    assert proposal["risks_and_mitigations"] == [{"risk": "오답 응대", "mitigation": "FAQ 범위 밖 질문은 사람에게 이관"}]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
