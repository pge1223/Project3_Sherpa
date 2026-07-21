# 작성자: 용준/Claude(2026-07-21)
# 목적: 대화형 아이디어 발전 회의(ideation-conversation)의 "질문 주제 구조화"
#       (question_topic/resolved_topics/pending_question_topic, roadmap 선행 조건,
#       전문가 의견 분량 제한) 기능을 실제 LLM 호출 없이 검증한다. 실제 사용자 테스트에서
#       "문제·목표 사용자·핵심 가치·공모전 적합성이 정리되지 않았는데 로드맵부터 질문"하고
#       "전문가 의견이 너무 길다"는 문제가 확인된 데 대한 회귀 테스트다.
#       기존 test_ideation_conv_graph.py/test_ideation_discovery_graph.py의 stub 패턴을 따르되,
#       질문/의견 노드(make_conv_question_node/make_conv_discussion_node)를 그래프 전체를
#       거치지 않고 직접 호출하는 테스트가 많다 — topic 우선순위·roadmap 선행 조건·분량
#       제한은 노드 하나의 입출력만으로 결정적으로 검증할 수 있어, 굳이 여러 턴짜리 대화를
#       구동할 필요가 없기 때문이다(빠르고 원인이 명확하다).
# import: 표준 라이브러리 json/sys/pathlib, pytest; ai/meeting/graph 패키지.

import json
import sys
from pathlib import Path

MEETING_DIR = Path(__file__).resolve().parents[1]  # ai/meeting
sys.path.insert(0, str(MEETING_DIR))

from graph import (  # noqa: E402
    initial_conv_state,
    reply_ideation_conversation,
    start_ideation_conversation,
)
from graph.ideation_conv_nodes import (  # noqa: E402
    make_conv_discussion_node,
    make_conv_question_node,
)

NOTICE_AND_CRITERIA = {
    "competition_name": "지역 소상공인 디지털전환 공모전",
    "notice_document": "실현가능성, 차별성을 평가한다.",
}
USER_IDEA = {"description": "소상공인이 손님 문의에 자동으로 답하는 챗봇"}


def _base_state(resolved_topics=None):
    state = initial_conv_state("TOPIC-TEST", NOTICE_AND_CRITERIA, USER_IDEA)
    return {**state, "resolved_topics": list(resolved_topics or [])}


def _llm_fixed_topic_and_sufficiency(question_topic: str, sufficiency_response: dict):
    """[질문 규칙] 호출에는 고정된 question_topic을, [판정 규칙] 호출에는 주어진 sufficiency_response를
    반환하는 최소 stub."""

    def llm_call(prompt: str) -> str:
        if "[질문 규칙]" in prompt:
            return json.dumps(
                {
                    "judgment": "판단",
                    "question": "질문",
                    "question_topic": question_topic,
                    "referenced_message_ids": [],
                    "evidence": [],
                },
                ensure_ascii=False,
            )
        if "[판정 규칙]" in prompt:
            return json.dumps(sufficiency_response, ensure_ascii=False)
        raise AssertionError(f"예상하지 못한 프롬프트입니다: {prompt[:200]}")

    return llm_call


# ---------------------------------------------------------------------------
# 1. question_topic이 state에 저장됨
# ---------------------------------------------------------------------------


def test_question_node_stores_question_topic_in_returned_update():
    def llm_call(prompt: str) -> str:
        return json.dumps(
            {
                "judgment": "판단",
                "question": "질문",
                "question_topic": "problem",
                "referenced_message_ids": [],
                "evidence": [],
            },
            ensure_ascii=False,
        )

    node = make_conv_question_node("planning_expert", "awaiting_planning_answer", llm_call)
    update = node(_base_state())
    assert update["pending_question_topic"] == "problem"
    assert update["phase"] == "awaiting_planning_answer"


# ---------------------------------------------------------------------------
# 2. answer로 다음 단계에 진입하면 해당 topic이 resolved_topics에 추가됨
# ---------------------------------------------------------------------------


def test_resolved_topics_gains_topic_when_answer_type_is_answer():
    llm = _llm_fixed_topic_and_sufficiency(
        "problem",
        {"answer_type": "answer", "reason": "충분", "follow_up_question": None, "clarification_response": None},
    )
    state = start_ideation_conversation(
        session_id="T2", notice_and_criteria=NOTICE_AND_CRITERIA, user_idea=USER_IDEA, llm_call=llm
    )
    assert state["pending_question_topic"] == "problem"

    state = reply_ideation_conversation(previous_state=state, user_message="문제는 반복 문의 응대입니다", llm_call=llm)
    assert state["resolved_topics"] == ["problem"]


# ---------------------------------------------------------------------------
# 3. clarification_request는 topic을 해결된 것으로 처리하지 않음
# ---------------------------------------------------------------------------


def test_resolved_topics_unchanged_on_clarification_request():
    llm = _llm_fixed_topic_and_sufficiency(
        "problem",
        {
            "answer_type": "clarification_request",
            "reason": "설명 요청",
            "follow_up_question": None,
            "clarification_response": "문제란 사용자가 겪는 불편을 뜻합니다.",
        },
    )
    state = start_ideation_conversation(
        session_id="T3", notice_and_criteria=NOTICE_AND_CRITERIA, user_idea=USER_IDEA, llm_call=llm
    )
    state = reply_ideation_conversation(previous_state=state, user_message="문제가 뭔가요?", llm_call=llm)
    assert state["resolved_topics"] == []


# ---------------------------------------------------------------------------
# 4. insufficient_answer는 topic을 해결된 것으로 처리하지 않음(재질문 진행 중 + 상한 도달 강제 진행)
# ---------------------------------------------------------------------------


def test_resolved_topics_unchanged_on_insufficient_answer_mid_retry():
    llm = _llm_fixed_topic_and_sufficiency(
        "problem",
        {
            "answer_type": "insufficient_answer",
            "reason": "불명확",
            "follow_up_question": "다시 설명해 주세요",
            "clarification_response": None,
        },
    )
    state = start_ideation_conversation(
        session_id="T4A", notice_and_criteria=NOTICE_AND_CRITERIA, user_idea=USER_IDEA, llm_call=llm
    )
    state = reply_ideation_conversation(previous_state=state, user_message="음...", llm_call=llm)
    assert state["resolved_topics"] == []
    assert state["answer_retry_count"] == 1


def test_resolved_topics_unchanged_when_forced_through_retry_cap():
    """재질문 상한(2회) 도달로 강제 진행되더라도, 실제로 명확히 답해진 게 아니므로
    resolved_topics에는 추가되지 않는다."""
    responses = [
        {"answer_type": "insufficient_answer", "reason": "불명확1", "follow_up_question": "다시요1", "clarification_response": None},
        {"answer_type": "insufficient_answer", "reason": "불명확2", "follow_up_question": "다시요2", "clarification_response": None},
        {"answer_type": "insufficient_answer", "reason": "불명확3", "follow_up_question": None, "clarification_response": None},
    ]

    def llm_call(prompt: str) -> str:
        if "[질문 규칙]" in prompt:
            return json.dumps(
                {
                    "judgment": "판단",
                    "question": "질문",
                    "question_topic": "problem",
                    "referenced_message_ids": [],
                    "evidence": [],
                },
                ensure_ascii=False,
            )
        if "[판정 규칙]" in prompt:
            return json.dumps(responses.pop(0), ensure_ascii=False)
        raise AssertionError(f"예상하지 못한 프롬프트입니다: {prompt[:200]}")

    state = start_ideation_conversation(
        session_id="T4B", notice_and_criteria=NOTICE_AND_CRITERIA, user_idea=USER_IDEA, llm_call=llm_call
    )
    state = reply_ideation_conversation(previous_state=state, user_message="모호1", llm_call=llm_call)
    assert state["answer_retry_count"] == 1
    state = reply_ideation_conversation(previous_state=state, user_message="모호2", llm_call=llm_call)
    assert state["answer_retry_count"] == 2

    state = reply_ideation_conversation(previous_state=state, user_message="모호3", llm_call=llm_call)
    assert state["phase"] == "awaiting_developer_answer"  # 강제로 다음 단계까지 진행됐지만
    assert "problem" not in state["resolved_topics"]  # topic은 해결된 것으로 처리되지 않는다.


# ---------------------------------------------------------------------------
# 5. 재질문 중 pending_question_topic 유지
# ---------------------------------------------------------------------------


def test_pending_question_topic_kept_during_follow_up_retry():
    llm = _llm_fixed_topic_and_sufficiency(
        "problem",
        {
            "answer_type": "insufficient_answer",
            "reason": "불명확",
            "follow_up_question": "다시 설명해 주세요",
            "clarification_response": None,
        },
    )
    state = start_ideation_conversation(
        session_id="T5", notice_and_criteria=NOTICE_AND_CRITERIA, user_idea=USER_IDEA, llm_call=llm
    )
    assert state["pending_question_topic"] == "problem"
    state = reply_ideation_conversation(previous_state=state, user_message="음...", llm_call=llm)
    assert state["pending_question_topic"] == "problem"  # 재질문 중에도 그대로 유지된다.


# ---------------------------------------------------------------------------
# 6. 새로운 질문으로 전환되면 pending_question_topic이 교체됨
# ---------------------------------------------------------------------------


def test_pending_question_topic_replaced_by_new_question():
    question_call_count = {"n": 0}

    def llm_call(prompt: str) -> str:
        if "[질문 규칙]" in prompt:
            question_call_count["n"] += 1
            topic = "problem" if question_call_count["n"] == 1 else "target_user"
            return json.dumps(
                {"judgment": "판단", "question": "질문", "question_topic": topic, "referenced_message_ids": [], "evidence": []},
                ensure_ascii=False,
            )
        if "[판정 규칙]" in prompt:
            return json.dumps(
                {"answer_type": "answer", "reason": "충분", "follow_up_question": None, "clarification_response": None},
                ensure_ascii=False,
            )
        raise AssertionError(f"예상하지 못한 프롬프트입니다: {prompt[:200]}")

    state = start_ideation_conversation(
        session_id="T6", notice_and_criteria=NOTICE_AND_CRITERIA, user_idea=USER_IDEA, llm_call=llm_call
    )
    assert state["pending_question_topic"] == "problem"

    state = reply_ideation_conversation(previous_state=state, user_message="문제는 반복 문의 응대입니다", llm_call=llm_call)
    assert state["pending_question_topic"] == "target_user"
    assert state["resolved_topics"] == ["problem"]


# ---------------------------------------------------------------------------
# 7. 필수 선행 주제가 확인되지 않으면 roadmap 질문을 허용하지 않음
# ---------------------------------------------------------------------------


def test_roadmap_question_blocked_when_prerequisites_missing():
    resolved = ["problem", "target_user", "core_value", "contest_fit"]  # mvp가 빠져 있다.
    call_count = {"n": 0}

    def llm_call(prompt: str) -> str:
        call_count["n"] += 1
        return json.dumps(
            {"judgment": "판단", "question": "로드맵 질문", "question_topic": "roadmap", "referenced_message_ids": [], "evidence": []},
            ensure_ascii=False,
        )

    node = make_conv_question_node("planning_expert", "awaiting_planning_answer", llm_call)
    update = node(_base_state(resolved))
    assert update["phase"] == "failed"
    assert update["failed_node"] == "question__planning_expert"
    assert call_count["n"] == 2  # 최초 1회 + 재시도 1회, 계속 무효했다.


# ---------------------------------------------------------------------------
# 8. 선행 주제가 모두 확인된 경우 roadmap 질문을 허용함
# ---------------------------------------------------------------------------


def test_roadmap_question_allowed_when_prerequisites_met():
    resolved = ["problem", "target_user", "core_value", "contest_fit", "mvp"]

    def llm_call(prompt: str) -> str:
        return json.dumps(
            {"judgment": "판단", "question": "로드맵 질문", "question_topic": "roadmap", "referenced_message_ids": [], "evidence": []},
            ensure_ascii=False,
        )

    node = make_conv_question_node("dev_expert", "awaiting_developer_answer", llm_call)
    update = node(_base_state(resolved))
    assert update["phase"] == "awaiting_developer_answer"
    assert update["pending_question_topic"] == "roadmap"


# ---------------------------------------------------------------------------
# 9. 이미 해결된 주제를 표현만 바꿔 반복 질문하지 않음(코드 강제)
# ---------------------------------------------------------------------------


def test_already_resolved_question_topic_is_rejected():
    resolved = ["problem"]
    call_count = {"n": 0}

    def llm_call(prompt: str) -> str:
        call_count["n"] += 1
        return json.dumps(
            {"judgment": "판단", "question": "질문", "question_topic": "problem", "referenced_message_ids": [], "evidence": []},
            ensure_ascii=False,
        )

    node = make_conv_question_node("planning_expert", "awaiting_planning_answer", llm_call)
    update = node(_base_state(resolved))
    assert update["phase"] == "failed"
    assert call_count["n"] == 2


# ---------------------------------------------------------------------------
# 10. 질문 응답의 question_topic 누락 또는 허용되지 않은 값 처리
# ---------------------------------------------------------------------------


def test_missing_question_topic_is_rejected():
    def llm_call(prompt: str) -> str:
        return json.dumps({"judgment": "판단", "question": "질문", "referenced_message_ids": [], "evidence": []}, ensure_ascii=False)

    node = make_conv_question_node("planning_expert", "awaiting_planning_answer", llm_call)
    update = node(_base_state())
    assert update["phase"] == "failed"


def test_invalid_question_topic_value_is_rejected():
    def llm_call(prompt: str) -> str:
        return json.dumps(
            {"judgment": "판단", "question": "질문", "question_topic": "budget", "referenced_message_ids": [], "evidence": []},
            ensure_ascii=False,
        )

    node = make_conv_question_node("planning_expert", "awaiting_planning_answer", llm_call)
    update = node(_base_state())
    assert update["phase"] == "failed"


# ---------------------------------------------------------------------------
# 14. 전문가 의견의 배열 항목 수 제한 검증(confirmed/unconfirmed 최대 3개)
# ---------------------------------------------------------------------------


def test_discussion_node_retries_then_fails_when_confirmed_exceeds_limit():
    payload = {
        "stance": "보완",
        "judgment": "판단",
        "reason": "근거",
        "suggestion": "제안",
        "confirmed": ["a", "b", "c", "d"],  # 4개 — 최대 3개 초과
        "unconfirmed": [],
        "referenced_message_ids": [],
        "evidence": [],
        "next_action": None,
    }
    call_count = {"n": 0}

    def llm_call(prompt: str) -> str:
        call_count["n"] += 1
        return json.dumps(payload, ensure_ascii=False)

    node = make_conv_discussion_node("planning_expert", speaks_second=False, llm_call=llm_call)
    update = node(_base_state())
    assert update["phase"] == "failed"
    assert call_count["n"] == 2


# ---------------------------------------------------------------------------
# 15. 긴 의견 응답은 재시도되고, 재시도 후에도 초과하면 안전하게 실패 처리됨(문자열을
#     강제로 자르지 않는다)
# ---------------------------------------------------------------------------


def test_discussion_node_retries_then_fails_when_judgment_too_long():
    long_judgment = "가" * 201  # 200자 상한 초과
    payload = {
        "stance": "보완",
        "judgment": long_judgment,
        "reason": "근거",
        "suggestion": "제안",
        "confirmed": [],
        "unconfirmed": [],
        "referenced_message_ids": [],
        "evidence": [],
        "next_action": None,
    }
    call_count = {"n": 0}

    def llm_call(prompt: str) -> str:
        call_count["n"] += 1
        return json.dumps(payload, ensure_ascii=False)

    node = make_conv_discussion_node("dev_expert", speaks_second=True, llm_call=llm_call)
    update = node(_base_state())
    assert update["phase"] == "failed"
    assert call_count["n"] == 2
    # 문자열이 잘리지 않고 그대로 실패 처리됐는지 — 잘린 judgment로 메시지가 만들어지지
    # 않는다(메시지 자체가 생성되지 않는다).
    assert "messages" not in update


def test_discussion_node_succeeds_when_within_length_limits():
    payload = {
        "stance": "보완",
        "judgment": "판단은 짧습니다",
        "reason": "근거도 짧습니다",
        "suggestion": "제안도 짧습니다",
        "confirmed": ["확인1"],
        "unconfirmed": ["미확인1"],
        "referenced_message_ids": [],
        "evidence": [],
        "next_action": None,
    }

    def llm_call(prompt: str) -> str:
        return json.dumps(payload, ensure_ascii=False)

    node = make_conv_discussion_node("planning_expert", speaks_second=False, llm_call=llm_call)
    update = node(_base_state())
    assert update.get("phase") != "failed"  # speaks_second=False면 phase 키 자체가 없을 수 있다.
    message = update["messages"][0]
    assert message["structured"]["judgment"] == "판단은 짧습니다"
    assert message["structured"]["confirmed"] == ["확인1"]


# ---------------------------------------------------------------------------
# 17. 구버전 state(resolved_topics/pending_question_topic 없음)에서도 KeyError 없이 동작
# ---------------------------------------------------------------------------


def test_reply_works_when_previous_state_missing_topic_fields():
    llm = _llm_fixed_topic_and_sufficiency(
        "problem",
        {"answer_type": "answer", "reason": "충분", "follow_up_question": None, "clarification_response": None},
    )
    state = start_ideation_conversation(
        session_id="T17", notice_and_criteria=NOTICE_AND_CRITERIA, user_idea=USER_IDEA, llm_call=llm
    )
    legacy_state = dict(state)
    del legacy_state["resolved_topics"]
    del legacy_state["pending_question_topic"]

    new_state = reply_ideation_conversation(
        previous_state=legacy_state, user_message="문제는 반복 문의 응대입니다", llm_call=llm
    )
    assert new_state["phase"] == "awaiting_developer_answer"
    # pending_question_topic 자체가 없었으므로 추가할 topic도 없다 — 핵심은 KeyError 없이
    # 안전하게 진행되는지다.
    assert new_state.get("resolved_topics", []) == []
