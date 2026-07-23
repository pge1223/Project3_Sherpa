from __future__ import annotations

import sys
from pathlib import Path

MEETING_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = MEETING_DIR.parents[1]
sys.path.insert(0, str(MEETING_DIR))
sys.path.insert(0, str(REPO_ROOT))

from ai.rag.evidence_linking.claim_grounding import ground_claims  # noqa: E402
from graph.ideation_conv_nodes import (  # noqa: E402
    _safe_call_structured_json,
    make_conv_discussion_node,
)
from graph.ideation_conv_state import initial_conv_state  # noqa: E402


class _AlwaysInvalidStreamingLLM:
    def __init__(self):
        self.calls = 0
        self.discards: list[tuple[str, str]] = []

    def __call__(self, prompt: str) -> str:
        self.calls += 1
        return '{"spoken_text": "필수 필드가 없는 임시 초안"}'

    def discard_streamed_prompt(self, prompt: str, reason: str) -> None:
        self.discards.append((prompt, reason))


def test_each_failed_attempt_is_traced_and_streamed_draft_is_discarded(monkeypatch):
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        "graph.ideation_conv_nodes.trace_event",
        lambda name, **fields: events.append((name, fields)),
    )
    llm = _AlwaysInvalidStreamingLLM()

    raw, ok, attempts = _safe_call_structured_json(
        llm,
        "same prompt",
        lambda value: "missing_or_empty_field:judgment" if not value.get("judgment") else None,
        "discussion__planning_expert",
    )

    failures = [fields for name, fields in events if name == "IDEATION_STRUCTURED_RESPONSE_VALIDATION_FAILED"]
    assert raw is None
    assert ok is False
    assert attempts == 2
    assert [item["attempt"] for item in failures] == [1, 2]
    assert [item["will_retry"] for item in failures] == [True, False]
    assert [reason for _, reason in llm.discards] == [
        "missing_or_empty_field:judgment",
        "missing_or_empty_field:judgment",
    ]


def test_discussion_uses_safe_expert_judgment_instead_of_failing_session(monkeypatch):
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        "graph.ideation_conv_nodes.trace_event",
        lambda name, **fields: events.append((name, fields)),
    )
    state = initial_conv_state(
        "SAFE-FALLBACK-1",
        {"competition_name": "테스트 공모전", "notice_document": "평가 기준"},
        {"description": "에너지 사용을 최적화하는 AI 서비스"},
        max_rounds=1,
    )
    llm = _AlwaysInvalidStreamingLLM()
    node = make_conv_discussion_node(
        "planning_expert",
        llm,
        ground_claims=lambda persona_id, claims, evidence: ground_claims(claims, evidence),
    )

    update = node(state)

    assert update.get("phase") != "failed"
    assert update.get("failed_node") is None
    assert update["previous_speaker"] == "planning_expert"
    assert update["expert_turn_count"] == 1
    message = update["messages"][0]
    assert "추가로 확인" in message["content"]
    assert message["structured"]["recommended_next_speaker"] == "dev_expert"
    assert message["structured"]["issue_resolved"] is False
    assert message["structured"]["safe_fallback"] is True
    assert message["structured"]["safe_fallback_reason"] == "structured_response_validation_failed_twice"
    assert message["claims"][0]["claim_type"] == "expert_judgment"
    assert message["claims"][0]["evidence_refs"] == []
    assert not any(claim["claim_type"] == "document_fact" for claim in message["claims"])
    assert any(name == "IDEATION_STRUCTURED_RESPONSE_SAFE_FALLBACK" for name, _ in events)
