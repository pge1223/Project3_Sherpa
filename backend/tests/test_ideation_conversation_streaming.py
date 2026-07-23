# 작성자: 용준/Claude(2026-07-21)
# 목적: POST /ideation-conversation/{session_id}/reply/stream(NDJSON 실시간 스트리밍)
#       검증. 실제 OpenAI 호출 대신 app.api.routes.ideation_conversation_preview::
#       _build_streaming_backends를 monkeypatch해 제어 가능한 가짜 스트리밍 LLM을 쓴다
#       (test_ideation_conversation_discovery.py가 _build_llm_call을 monkeypatch하는
#       것과 같은 패턴). 그래프/노드 코드는 전혀 건드리지 않는다 — 이 테스트는 API 계층
#       (스트리밍 브리지, 이벤트 조립, 세션 락)만 검증한다.
# import: fastapi.testclient, pytest; app.api.routes.ideation_conversation_preview 모듈.

import json
import re
import sys
import threading
import time
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


def _discussion_payload_for(prompt: str) -> dict:
    """[의견 규칙] 스텁 응답을 만든다 — 동기식(_sync_stub_llm_call)과 스트리밍
    (_FakeStreamState) 양쪽에서 똑같이 재사용해, "스트리밍 결과와 동기식 결과가 의미상
    같다"는 테스트가 서로 다른 스텁 문구 차이 때문에 실패하지 않게 한다. 용준/Claude
    (2026-07-21, 요청: 전문가 라운드테이블 전환) 이후 사용자에게 실시간으로 보이는 첫
    스트리밍 대상은 1:1 인터뷰 질문이 아니라 라운드테이블의 전문가 의견(discussion)이다."""
    is_planning = "당신은 AI Review Board의 기획 전문가입니다" in prompt
    is_dev = not is_planning
    speaker = "planning_expert" if is_planning else "dev_expert"
    return {
        "stance": "보완",
        "judgment": f"[{speaker}] 한글 판단 내용\n줄바꿈도 있습니다",
        "reason": f"[{speaker}] 판단 근거 \"인용부호\" 포함",
        "suggestion": f"[{speaker}] 제안 내용입니다",
        "interim_conclusion": f"[{speaker}] 현재 임시 결론입니다",
        "responding_to": "상대 전문가가 방금 말한 판단" if is_dev else None,
        "agreement": "동의 지점입니다" if is_dev else "",
        "concern": "",
        "confirmed": [],
        "unconfirmed": [],
        "referenced_message_ids": [],
        "evidence": [],
        "next_action": "await_user_decision" if is_dev else None,
    }


def _facilitator_summary_payload_for(prompt: str) -> dict:
    return {
        "agreements": [],
        "disagreements": [],
        "facilitator_summary": "두 전문가가 이번 라운드 의견을 정리했습니다.",
        "needs_user_decision": False,
        "user_question": None,
    }


# 가은/Claude(2026-07-22, 캔버스 자동 갱신) — 매 라운드 끝의 canvas_update 노드 응답.
# 스트리밍 대상이 아니라(_stream_plan_for가 None을 반환) call_chat_completion 쪽으로 온다.
def _canvas_payload() -> dict:
    return {
        "problem": "[canvas] 문제 상황",
        "target_user": "[canvas] 타깃 사용자",
        "core_value": "[canvas] 핵심 가치",
        "solution": "[canvas] 해결 방식",
        "differentiation": "[canvas] 차별점",
        "feasibility": "medium",
        "risks": ["[canvas] 리스크"],
        "contest_fit": "[canvas] 심사기준 대응",
    }


def _sync_stub_llm_call(session_id: str, model: str):
    """기존 동기식 /start, /reply(비교용)에 쓰는 완성 응답 스텁 — 스트리밍 스텁과 정확히
    같은 내용을 반환해야 "스트리밍 결과와 동기식 결과가 의미상 같다"를 비교할 수 있다."""

    def llm_call(prompt: str) -> str:
        if "[의견 규칙]" in prompt:
            return json.dumps(_discussion_payload_for(prompt), ensure_ascii=False)
        if "[진행자 정리 규칙]" in prompt:
            return json.dumps(_facilitator_summary_payload_for(prompt), ensure_ascii=False)
        if "[질문 규칙]" in prompt:
            is_planning = "당신은 AI Review Board의 기획 전문가입니다" in prompt
            speaker = "planning_expert" if is_planning else "dev_expert"
            return json.dumps(
                {
                    "judgment": f"[{speaker}] 한글 판단 내용\n줄바꿈도 있습니다",
                    "question": f"[{speaker}] 핵심 질문 \"인용부호\" 포함",
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
        if "[캔버스 갱신 규칙]" in prompt:
            return json.dumps(_canvas_payload(), ensure_ascii=False)
        raise AssertionError(f"예상하지 못한 프롬프트: {prompt[:150]}")

    return llm_call


class _FakeStreamState:
    """[의견 규칙]/[진행자 정리 규칙] 스트리밍 호출을 몇 글자씩 쪼개 흉내내는 가짜 백엔드.
    invalid_first=True면 전체 스트림에서 가장 먼저 들어오는 호출(항상 기획 위원의 최초
    의견) 한 번만 검증 실패를 유도해 재시도 시나리오를 만든다."""

    def __init__(self, chunk_size=3, delay=0.0, invalid_first=False):
        self.chunk_size = chunk_size
        self.delay = delay
        self.invalid_first = invalid_first
        self.call_counts = {"discussion": 0, "facilitator_summary": 0}
        self._first_call_done = False

    def _discussion_payload(self, prompt: str) -> dict:
        if self.invalid_first and not self._first_call_done:
            self._first_call_done = True
            return {"judgment": "", "reason": ""}  # 검증 실패 유도 -> 재시도
        self._first_call_done = True
        return _discussion_payload_for(prompt)

    def build(self):
        def stream_chat_completion(prompt: str):
            if "[의견 규칙]" in prompt:
                self.call_counts["discussion"] += 1
                payload = self._discussion_payload(prompt)
            elif "[진행자 정리 규칙]" in prompt:
                self.call_counts["facilitator_summary"] += 1
                payload = _facilitator_summary_payload_for(prompt)
            else:
                raise AssertionError(f"스트리밍 대상이 아닌 프롬프트가 stream_chat_completion으로 왔습니다: {prompt[:100]}")
            raw = json.dumps(payload, ensure_ascii=False)
            for i in range(0, len(raw), self.chunk_size):
                if self.delay:
                    time.sleep(self.delay)
                yield raw[i : i + self.chunk_size]

        def call_chat_completion(prompt: str) -> str:
            # 가은/Claude(2026-07-22, 캔버스 자동 갱신) — canvas_update는 화면 메시지를 만들지
            # 않아 스트리밍 대상이 아니고, 항상 이 동기식 경로로 온다.
            if "[캔버스 갱신 규칙]" in prompt:
                return json.dumps(_canvas_payload(), ensure_ascii=False)
            # 가은/Claude(2026-07-22, 회의 시작 대기 체감 개선 1단계) — /start/stream의
            # discovery 경로(후보 생성/검토)도 화면 메시지가 없는 phase-only 호출이라 이
            # 동기식 경로로 온다(test_ideation_conversation_discovery.py의 stub과 같은 payload).
            if "[후보 생성 규칙]" in prompt:
                return json.dumps(
                    {
                        "contest_analysis": {
                            "purpose": "p", "key_criteria": ["a"], "required_tech_or_theme": ["b"],
                            "suitable_problem_domains": ["c"], "constraints": ["d"], "unknown_from_notice": ["e"],
                        },
                        "candidates": [
                            {
                                "candidate_id": "candidate_1", "title": "후보1", "problem": "문제1",
                                "target_user": "사용자1", "usage_scenario": "상황1", "core_value": "가치1",
                                "solution": "해결1", "main_features": ["기능1"], "differentiation": "차별1",
                                "contest_fit": "적합1", "success_metrics": ["지표1"],
                            },
                            {
                                "candidate_id": "candidate_2", "title": "후보2", "problem": "문제2",
                                "target_user": "사용자2", "usage_scenario": "상황2", "core_value": "가치2",
                                "solution": "해결2", "main_features": ["기능2"], "differentiation": "차별2",
                                "contest_fit": "적합2", "success_metrics": ["지표2"],
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
                                "candidate_id": "candidate_1", "required_data": ["d1"], "technical_approach": "t1",
                                "mvp_scope": "m1", "feasibility": "high", "risks": ["r1"], "dev_notes": None,
                            },
                            {
                                "candidate_id": "candidate_2", "required_data": ["d2"], "technical_approach": "t2",
                                "mvp_scope": "m2", "feasibility": "medium", "risks": ["r2"], "dev_notes": None,
                            },
                        ]
                    },
                    ensure_ascii=False,
                )
            raise AssertionError(f"예상하지 못한 프롬프트: {prompt[:100]}")

        return stream_chat_completion, call_chat_completion


@pytest.fixture(autouse=True)
def _enable_flags(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_IDEATION_PREVIEW", True)
    monkeypatch.setattr(settings, "ENABLE_IDEATION_STREAMING", True)
    monkeypatch.setattr(conv_route, "_build_llm_call", _sync_stub_llm_call)


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(conv_route.router)
    return TestClient(app)


def _start_session(client: TestClient) -> str:
    resp = client.post(
        "/ideation-conversation/start",
        json={
            "competition_name": "데모 공모전",
            "user_idea": "소상공인이 손님 문의에 자동으로 답하는 챗봇",
        },
    )
    assert resp.status_code == 200
    return resp.json()["session_id"]


def _read_ndjson_events(response) -> list[dict]:
    events = []
    for line in response.iter_lines():
        if not line:
            continue
        events.append(json.loads(line))
    return events


def test_streaming_disabled_returns_404(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_IDEATION_STREAMING", False)
    session_id = _start_session(client)
    resp = client.post(f"/ideation-conversation/{session_id}/reply/stream", json={"message": "답변1"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# /start/stream — 가은/Claude(2026-07-22, 요청: 회의 시작 대기 체감 개선 1단계)
# ---------------------------------------------------------------------------


def test_start_stream_disabled_returns_404(client: TestClient, monkeypatch):
    """플래그가 꺼져 있으면 404 — 프론트가 이 응답을 보고 동기식 /start로 폴백한다."""
    monkeypatch.setattr(settings, "ENABLE_IDEATION_STREAMING", False)
    resp = client.post(
        "/ideation-conversation/start/stream",
        json={"competition_name": "데모 공모전", "user_idea": ""},
    )
    assert resp.status_code == 404


def test_start_stream_discovery_emits_phase_events_then_final_state(client: TestClient, monkeypatch):
    """board의 실제 경로(discovery, user_idea 없음): 후보 생성/실현 가능성 검토는 화면
    메시지를 만들지 않으므로 message_delta 없이 phase 이벤트만 나가고, 마지막에 최종
    state 이벤트가 온다. 세션도 정상 생성되어 이후 GET으로 이어받을 수 있어야 한다."""
    fake = _FakeStreamState(chunk_size=4)
    monkeypatch.setattr(conv_route, "_build_streaming_backends", lambda session_id, model: fake.build())

    with client.stream(
        "POST",
        "/ideation-conversation/start/stream",
        json={"competition_name": "데모 공모전", "user_idea": ""},
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/x-ndjson")
        events = _read_ndjson_events(resp)

    types = [e["type"] for e in events]
    assert types[-1] == "state"
    phase_labels = [e.get("label", "") for e in events if e["type"] == "phase"]
    assert any("아이디어 후보를 만들고" in label for label in phase_labels)
    assert any("실현 가능성" in label for label in phase_labels)
    assert "message_delta" not in types  # discovery 시작은 화면 메시지를 만들지 않는다.

    final_state = events[-1]["state"]
    assert final_state["phase"] == "awaiting_candidate_selection"
    assert len(final_state["idea_candidates"]) == 2
    # 세션이 스토어에 저장돼 재접속(GET)으로 이어받을 수 있다.
    get_resp = client.get(f"/ideation-conversation/{final_state['session_id']}")
    assert get_resp.status_code == 200


def test_start_stream_refinement_streams_roundtable_messages(client: TestClient, monkeypatch):
    """refinement 모드(user_idea 있음)로 시작하면 라운드테이블 발언이 reply/stream과
    동일하게 message_delta(타이핑 효과)로 스트리밍된다 — 같은 make_streaming_llm_call을
    그대로 쓰므로 추가 구현 없이 따라오는 동작을 고정한다."""
    fake = _FakeStreamState(chunk_size=4)
    monkeypatch.setattr(conv_route, "_build_streaming_backends", lambda session_id, model: fake.build())

    with client.stream(
        "POST",
        "/ideation-conversation/start/stream",
        json={"competition_name": "데모 공모전", "user_idea": "소상공인 손님 문의 자동 응대 챗봇"},
    ) as resp:
        events = _read_ndjson_events(resp)

    types = [e["type"] for e in events]
    assert "message_start" in types
    assert "message_delta" in types
    assert types[-1] == "state"
    assert events[-1]["state"]["phase"] == "awaiting_user_decision"


def test_stream_event_order_message_start_delta_end_state(client: TestClient, monkeypatch):
    fake = _FakeStreamState(chunk_size=4)
    monkeypatch.setattr(conv_route, "_build_streaming_backends", lambda session_id, model: fake.build())

    session_id = _start_session(client)
    with client.stream(
        "POST", f"/ideation-conversation/{session_id}/reply/stream", json={"message": "타깃은 동네 카페 사장님입니다"}
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/x-ndjson")
        events = _read_ndjson_events(resp)

    types = [e["type"] for e in events]
    assert "message_start" in types
    assert "message_end" in types
    assert types[-1] == "state"
    delta_indices = [i for i, t in enumerate(types) if t == "message_delta"]
    assert delta_indices, "message_delta 이벤트가 하나도 없습니다"

    # 용준/Claude(2026-07-21, 요청: 전문가 라운드테이블 전환) — 한 번의 /reply/stream 호출
    # 안에서 기획 위원 -> 개발 위원 -> 진행자 순으로 여러 메시지가 순차적으로 스트리밍된다.
    # 각 메시지는 자신의 message_start/message_delta.../message_end 세트 안에서만 등장하고
    # (겹치지 않고), 이전 메시지가 끝나야 다음 메시지가 시작돼야 한다.
    open_id = None
    seen_ids: list[str] = []
    for e in events:
        if e["type"] == "message_start":
            assert open_id is None, "이전 메시지가 끝나기 전에 새 메시지가 시작됐다"
            open_id = e["message_id"]
            seen_ids.append(open_id)
        elif e["type"] == "message_delta":
            assert e["message_id"] == open_id, "delta가 현재 열린 메시지를 가리키지 않는다"
        elif e["type"] == "message_end":
            assert e["message_id"] == open_id
            open_id = None
    assert open_id is None
    assert len(seen_ids) >= 1


def test_korean_text_reassembles_correctly_across_small_chunks(client: TestClient, monkeypatch):
    fake = _FakeStreamState(chunk_size=1)  # 극단적으로 잘게 쪼갠다(멀티바이트 경계 포함).
    monkeypatch.setattr(conv_route, "_build_streaming_backends", lambda session_id, model: fake.build())

    session_id = _start_session(client)
    with client.stream(
        "POST", f"/ideation-conversation/{session_id}/reply/stream", json={"message": "답변1"}
    ) as resp:
        events = _read_ndjson_events(resp)

    deltas = "".join(e["delta"] for e in events if e["type"] == "message_delta")
    assert "한글 판단 내용" in deltas
    assert "줄바꿈도 있습니다" in deltas
    assert '인용부호' in deltas
    # 용준/Claude(2026-07-21, 요청: 전문가 라운드테이블 전환) — 헤더가 역할별로 다르다.
    # 기획 위원이 라운드테이블의 첫 발언자이므로 기획 위원 헤더가 반드시 나타난다.
    assert "[기획 관점]" in deltas
    assert "[임시 결론]" in deltas
    # message_delta 텍스트 안에 JSON 구조(중괄호·필드명)가 노출되면 안 된다.
    assert "judgment" not in deltas
    assert "interim_conclusion" not in deltas
    assert "{" not in deltas and "}" not in deltas


def test_streaming_final_state_matches_sync_reply_semantically(client: TestClient, monkeypatch):
    fake = _FakeStreamState(chunk_size=5)
    monkeypatch.setattr(conv_route, "_build_streaming_backends", lambda session_id, model: fake.build())

    stream_session_id = _start_session(client)
    with client.stream(
        "POST", f"/ideation-conversation/{stream_session_id}/reply/stream", json={"message": "답변1"}
    ) as resp:
        events = _read_ndjson_events(resp)
    stream_state = next(e["state"] for e in events if e["type"] == "state")

    sync_session_id = _start_session(client)
    sync_resp = client.post(f"/ideation-conversation/{sync_session_id}/reply", json={"message": "답변1"})
    assert sync_resp.status_code == 200
    sync_state = sync_resp.json()

    # 용준/Claude(2026-07-21, 요청: 전문가 라운드테이블 전환) — "awaiting_user_decision"
    # 상태에서 사용자가 자유 발언을 남기면 새 라운드(기획 -> 개발 -> 진행자)가 실행되고,
    # dev 스텁이 next_action="await_user_decision"을 반환하므로 다시 "awaiting_user_decision"
    # 으로 멈춘다.
    assert stream_state["phase"] == sync_state["phase"] == "awaiting_user_decision"
    stream_last = stream_state["messages"][-1]
    sync_last = sync_state["messages"][-1]
    assert stream_last["speaker_id"] == sync_last["speaker_id"]
    assert stream_last["content"] == sync_last["content"]


def test_multiple_persona_messages_keep_order_and_speaker_id(client: TestClient, monkeypatch):
    """용준/Claude(2026-07-21, 요청: 전문가 라운드테이블 전환) — 사용자가 "awaiting_user_decision"
    상태에서 자유 발언을 남기면 기획 위원 -> 개발 위원 -> 진행자 순으로 라운드 전체가
    스트리밍된다. 스트리밍된 message_start들의 speaker_id 순서가 실제 대화 순서와
    일치하는지 확인한다."""
    fake = _FakeStreamState(chunk_size=6)
    monkeypatch.setattr(conv_route, "_build_streaming_backends", lambda session_id, model: fake.build())

    session_id = _start_session(client)
    with client.stream(
        "POST", f"/ideation-conversation/{session_id}/reply/stream", json={"message": "답변1"}
    ) as resp:
        events = _read_ndjson_events(resp)

    starts = [e for e in events if e["type"] == "message_start"]
    assert [s["speaker_id"] for s in starts] == ["planning_expert", "dev_expert", "ideation_facilitator"]
    state_event = next(e for e in events if e["type"] == "state")
    speakers = [m["speaker_id"] for m in state_event["state"]["messages"]]
    # user(답변1) 다음에 기획 -> 개발 -> 진행자 순으로 이어진다.
    assert speakers[-4:] == ["user", "planning_expert", "dev_expert", "ideation_facilitator"]


def test_retry_emits_message_reset_before_new_message_start(client: TestClient, monkeypatch):
    fake = _FakeStreamState(chunk_size=4, invalid_first=True)
    monkeypatch.setattr(conv_route, "_build_streaming_backends", lambda session_id, model: fake.build())

    session_id = _start_session(client)
    with client.stream(
        "POST", f"/ideation-conversation/{session_id}/reply/stream", json={"message": "답변1"}
    ) as resp:
        events = _read_ndjson_events(resp)

    types = [e["type"] for e in events]
    # 용준/Claude(2026-07-21, 요청: 전문가 라운드테이블 전환) — 검증 실패는 라운드의 첫
    # 발언(기획 위원)에서만 유도된다(재시도 1회로 성공). 이어지는 개발 위원(1회)·진행자
    # (1회)는 정상적으로 성공하므로, 전체 메시지 세트는 4개(기획 실패분 + 기획 재시도분 +
    # 개발 + 진행자)다.
    assert types.count("message_reset") == 1
    assert types.count("message_start") == 4
    assert types.count("message_end") == 4
    reset_event = next(e for e in events if e["type"] == "message_reset")
    first_start = [e for e in events if e["type"] == "message_start"][0]
    assert reset_event["message_id"] == first_start["message_id"]
    assert fake.call_counts["discussion"] == 3  # 기획(최초 실패 1 + 재시도 1) + 개발(1)
    assert fake.call_counts["facilitator_summary"] == 1


def test_llm_failure_emits_error_event(client: TestClient, monkeypatch):
    def broken_backends(session_id, model):
        def stream_chat_completion(prompt):
            raise RuntimeError("네트워크 오류 시뮬레이션")

        def call_chat_completion(prompt):
            raise RuntimeError("네트워크 오류 시뮬레이션")

        return stream_chat_completion, call_chat_completion

    monkeypatch.setattr(conv_route, "_build_streaming_backends", broken_backends)

    session_id = _start_session(client)
    with client.stream(
        "POST", f"/ideation-conversation/{session_id}/reply/stream", json={"message": "답변1"}
    ) as resp:
        events = _read_ndjson_events(resp)

    types = [e["type"] for e in events]
    assert "error" in types
    error_event = next(e for e in events if e["type"] == "error")
    assert error_event["code"] == "llm_failure"
    assert "네트워크 오류 시뮬레이션" not in error_event["message"]  # 원본 예외 메시지를 그대로 노출하지 않는다.


def test_session_state_not_corrupted_after_stream_and_llm_failure(client: TestClient, monkeypatch):
    """오류가 나도 세션 state는 실패 이전의 유효한 상태로 남아 있어야 한다(손상되지 않음).
    실패 후 다시 정상 스텁으로 answer 재전송하면 정상 진행되는지까지 확인한다."""

    def broken_backends(session_id, model):
        def stream_chat_completion(prompt):
            raise RuntimeError("boom")

        def call_chat_completion(prompt):
            raise RuntimeError("boom")

        return stream_chat_completion, call_chat_completion

    monkeypatch.setattr(conv_route, "_build_streaming_backends", broken_backends)
    session_id = _start_session(client)
    with client.stream(
        "POST", f"/ideation-conversation/{session_id}/reply/stream", json={"message": "답변1"}
    ) as resp:
        _read_ndjson_events(resp)

    # 세션이 여전히 조회 가능하고(손상/삭제되지 않음), phase도 실패 이전 그대로다.
    # 용준/Claude(2026-07-21, 요청: 전문가 라운드테이블 전환) — 세션은 시작 직후 이미
    # 라운드테이블 한 라운드를 마치고 "awaiting_user_decision"으로 멈춰 있었다.
    get_resp = client.get(f"/ideation-conversation/{session_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["phase"] == "awaiting_user_decision"

    # 락도 정상적으로 풀려서 다음 요청(정상 스텁)이 처리된다.
    fake = _FakeStreamState(chunk_size=4)
    monkeypatch.setattr(conv_route, "_build_streaming_backends", lambda sid, m: fake.build())
    resp2 = client.post(f"/ideation-conversation/{session_id}/reply", json={"message": "답변1"})
    assert resp2.status_code == 200
    assert resp2.json()["phase"] == "awaiting_user_decision"


def test_concurrent_reply_to_same_session_returns_409(client: TestClient, monkeypatch):
    # 용준/Claude(2026-07-21, 요청: 전문가 라운드테이블 전환) — 한 번의 /reply/stream 호출이
    # 이제 기획/개발/진행자 3개 메시지를 순차 스트리밍하므로(과거 1개 메시지 대비 총 대기
    # 시간이 늘어난다), chunk당 delay를 줄이고 join 타임아웃을 넉넉히 잡는다.
    fake = _FakeStreamState(chunk_size=3, delay=0.02)
    monkeypatch.setattr(conv_route, "_build_streaming_backends", lambda session_id, model: fake.build())

    session_id = _start_session(client)
    results = {}

    def first_call():
        with client.stream(
            "POST", f"/ideation-conversation/{session_id}/reply/stream", json={"message": "답변1"}
        ) as resp:
            results["first_status"] = resp.status_code
            list(resp.iter_lines())  # 끝까지 소비해서 워커가 마무리되게 한다.

    thread = threading.Thread(target=first_call)
    thread.start()
    time.sleep(0.05)  # 첫 요청이 락을 잡을 시간을 준다.
    second_resp = client.post(f"/ideation-conversation/{session_id}/reply", json={"message": "동시 요청"})
    thread.join(timeout=15)

    assert results.get("first_status") == 200
    assert second_resp.status_code == 409


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
