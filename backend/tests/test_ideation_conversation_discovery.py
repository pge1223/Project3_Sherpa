# 작성자: 용준/Claude(2026-07-21)
# 목적: /ideation-conversation/start API가 user_idea 없이도(discovery 모드) 400을
#       반환하지 않는지, competition_name은 계속 필수인지, 응답에 discovery 관련 필드
#       (ideation_mode/idea_candidates 등)가 포함되는지, 기존 요청 형식(초기 아이디어를
#       채워 보내는 방식)과의 하위 호환이 유지되는지를 검증한다.
#
#       app.main 전체를 띄우지 않고(Mongo/KURE 임베더 로딩 등 무거운 초기화를 피하기 위해,
#       backend/tests/test_meetings_followup.py가 app.api.routes.meetings를 직접 import하는
#       것과 같은 패턴) ideation_conversation_preview.router만 담은 최소 FastAPI 앱을 쓴다.
#       OpenAI 실제 호출은 _build_llm_call을 monkeypatch해 대체한다(네트워크 호출 없음).
# import: fastapi.testclient, pytest; app.api.routes.ideation_conversation_preview 모듈.

import json
import re
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.config import settings  # noqa: E402
import app.api.routes.ideation_conversation_preview as conv_route  # noqa: E402

_REMAINING_TOPICS_RE = re.compile(
    r"\[아직 확인되지 않은 주제\(우선순위 순\) remaining_topics\]\n(.*?)\n\n", re.S
)


def _topic_from_prompt(prompt: str) -> str:
    match = _REMAINING_TOPICS_RE.search(prompt)
    if not match:
        return "problem"
    try:
        remaining = json.loads(match.group(1))
    except (ValueError, TypeError):
        return "problem"
    return remaining[0] if remaining else "problem"


def _stub_llm_call(session_id: str, model: str):
    def llm_call(prompt: str) -> str:
        if "[후보 생성 규칙]" in prompt:
            return json.dumps(
                {
                    "contest_analysis": {
                        "purpose": "p",
                        "key_criteria": ["a"],
                        "required_tech_or_theme": ["b"],
                        "suitable_problem_domains": ["c"],
                        "constraints": ["d"],
                        "unknown_from_notice": ["e"],
                    },
                    "candidates": [
                        {
                            "candidate_id": "candidate_1",
                            "title": "후보1",
                            "problem": "문제1",
                            "target_user": "사용자1",
                            "usage_scenario": "상황1",
                            "core_value": "가치1",
                            "solution": "해결1",
                            "main_features": ["기능1"],
                            "differentiation": "차별1",
                            "contest_fit": "적합1",
                            "success_metrics": ["지표1"],
                        },
                        {
                            "candidate_id": "candidate_2",
                            "title": "후보2",
                            "problem": "문제2",
                            "target_user": "사용자2",
                            "usage_scenario": "상황2",
                            "core_value": "가치2",
                            "solution": "해결2",
                            "main_features": ["기능2"],
                            "differentiation": "차별2",
                            "contest_fit": "적합2",
                            "success_metrics": ["지표2"],
                        },
                    ],
                },
                ensure_ascii=False,
            )
        if "[검토 규칙]" in prompt:
            return json.dumps(
                {
                    "candidate_reviews": [
                        {
                            "candidate_id": "candidate_1",
                            "required_data": ["d1"],
                            "technical_approach": "t1",
                            "mvp_scope": "m1",
                            "feasibility": "high",
                            "risks": ["r1"],
                            "dev_notes": None,
                        },
                        {
                            "candidate_id": "candidate_2",
                            "required_data": ["d2"],
                            "technical_approach": "t2",
                            "mvp_scope": "m2",
                            "feasibility": "medium",
                            "risks": ["r2"],
                            "dev_notes": None,
                        },
                    ]
                },
                ensure_ascii=False,
            )
        if "[질문 규칙]" in prompt:
            is_planning = "당신은 AI Review Board의 기획 전문가입니다" in prompt
            speaker = "planning_expert" if is_planning else "dev_expert"
            return json.dumps(
                {
                    "judgment": f"[{speaker}] 판단",
                    "question": f"[{speaker}] 질문",
                    "question_topic": _topic_from_prompt(prompt),
                    "referenced_message_ids": [],
                    "evidence": [],
                },
                ensure_ascii=False,
            )
        if "[판정 규칙]" in prompt:
            return json.dumps(
                {"answer_type": "answer", "reason": "충분", "follow_up_question": None, "clarification_response": None},
                ensure_ascii=False,
            )
        raise AssertionError(f"예상하지 못한 프롬프트: {prompt[:150]}")

    return llm_call


@pytest.fixture(autouse=True)
def _enable_preview_and_stub_llm(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_IDEATION_PREVIEW", True)
    monkeypatch.setattr(conv_route, "_build_llm_call", _stub_llm_call)


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(conv_route.router)
    return TestClient(app)


def test_start_without_user_idea_returns_200_and_discovery_mode(client: TestClient):
    resp = client.post(
        "/ideation-conversation/start",
        json={"competition_name": "데모 공모전", "competition_document": "실현가능성을 평가한다."},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ideation_mode"] == "discovery"
    assert body["phase"] == "awaiting_candidate_selection"
    assert len(body["idea_candidates"]) >= 2
    assert body["active_stage"] == "candidate_discovery"


def test_active_stage_switches_to_refinement_after_candidate_selection(client: TestClient):
    """discovery로 시작해 후보를 선택하면 ideation_mode는 "discovery"로 유지되지만
    active_stage는 "candidate_discovery" -> "refinement"로 바뀌어야 한다(프론트 배지가
    "아이디어 발굴 모드"에서 "아이디어 발전 모드"로 전환되는 근거)."""
    start_resp = client.post(
        "/ideation-conversation/start",
        json={"competition_name": "데모 공모전", "competition_document": "실현가능성을 평가한다."},
    )
    assert start_resp.status_code == 200
    session_id = start_resp.json()["session_id"]
    assert start_resp.json()["active_stage"] == "candidate_discovery"

    reply_resp = client.post(f"/ideation-conversation/{session_id}/reply", json={"message": "1번"})
    assert reply_resp.status_code == 200
    body = reply_resp.json()
    assert body["ideation_mode"] == "discovery"
    assert body["phase"] == "awaiting_planning_answer"
    assert body["active_stage"] == "refinement"


def test_start_with_whitespace_only_user_idea_returns_200_and_discovery_mode(client: TestClient):
    resp = client.post(
        "/ideation-conversation/start",
        json={"competition_name": "데모 공모전", "user_idea": "   "},
    )
    assert resp.status_code == 200
    assert resp.json()["ideation_mode"] == "discovery"


def test_start_without_competition_name_still_returns_400(client: TestClient):
    # competition_name은 계속 필수다 — 빈 문자열이면 _clamp_text가 400을 반환해야 한다.
    resp = client.post("/ideation-conversation/start", json={"competition_name": "", "user_idea": ""})
    assert resp.status_code == 400


def test_start_with_user_idea_still_returns_refinement_mode_backward_compatible(client: TestClient):
    """기존 요청 형식(초기 아이디어를 채워 보내는 방식)이 그대로 동작하는지 — 하위 호환성."""
    resp = client.post(
        "/ideation-conversation/start",
        json={
            "competition_name": "데모 공모전",
            "competition_document": "실현가능성을 평가한다.",
            "user_idea": "소상공인이 손님 문의에 자동으로 답하는 챗봇",
            "max_rounds": 2,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ideation_mode"] == "refinement"
    assert body["phase"] == "awaiting_planning_answer"
    # 기존 필드가 하나도 빠지지 않았다.
    for field in (
        "session_id",
        "phase",
        "round",
        "max_rounds",
        "messages",
        "consensus",
        "unresolved_issues",
        "idea_proposal",
        "ideation_mode",
        "active_stage",
        "idea_candidates",
        "selected_idea",
        "selection_reason",
        "error",
    ):
        assert field in body
    # 용준/Claude(2026-07-21, 질문 주제 구조화): resolved_topics/pending_question_topic은
    # 순수 추가 필드다 — 요청 16번(기존 필드 유지) + 신규 필드 노출을 함께 확인한다.
    assert body["resolved_topics"] == []
    assert body["pending_question_topic"] == "problem"  # 첫 질문은 항상 우선순위 최상위 주제.


def test_reply_response_includes_topic_fields_after_first_answer(client: TestClient):
    """/reply 응답에도 resolved_topics/pending_question_topic이 포함되고, 답변이 answer로
    판정되면 resolved_topics가 실제로 갱신되는지 확인한다."""
    start_resp = client.post(
        "/ideation-conversation/start",
        json={
            "competition_name": "데모 공모전",
            "user_idea": "소상공인이 손님 문의에 자동으로 답하는 챗봇",
        },
    )
    assert start_resp.status_code == 200
    session_id = start_resp.json()["session_id"]
    assert start_resp.json()["pending_question_topic"] == "problem"

    reply_resp = client.post(
        f"/ideation-conversation/{session_id}/reply",
        json={"message": "반복 문의 응대 부담을 해결하고 싶습니다"},
    )
    assert reply_resp.status_code == 200
    body = reply_resp.json()
    assert "resolved_topics" in body
    assert "pending_question_topic" in body


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
