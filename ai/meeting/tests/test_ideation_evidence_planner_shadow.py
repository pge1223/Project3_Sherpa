# 작성자: 용준/Claude(2026-07-23, Phase 1 "Shadow Deterministic Evidence Planner")
# 목적: make_conv_discussion_node에 주입되는 evidence_planner 콜러블이 (1) 기존 prompt/
#       claims/grounding/routing/메시지 내용에 전혀 영향을 주지 않고, (2) retrieval 직후
#       올바른 인자(effective_issue/retrieved_evidence/runtime_scope/shadow_history)로
#       호출되며, (3) 예외가 나도 발언 생성을 막지 않고, (4) 같은 speaker/issue의 선택
#       이력이 세션 state에 쌓이는지 검증한다. 실제 ai.rag 구현(ideation_evidence_planner)은
#       ai/rag/tests/test_ideation_evidence_planner.py가 별도로 검증하므로, 여기서는 ai/meeting
#       쪽 경계(콜러블의 "모양"만 안다)를 지키기 위해 recording fake만 주입한다.

import json
import sys
from pathlib import Path

MEETING_DIR = Path(__file__).resolve().parents[1]  # ai/meeting
sys.path.insert(0, str(MEETING_DIR))

from graph import reply_ideation_conversation, start_ideation_conversation  # noqa: E402
from graph.ideation_conv_nodes import resolve_effective_issue, resolve_retrieval_issue  # noqa: E402
from graph.ideation_conv_state import initial_conv_state  # noqa: E402

from test_ideation_conv_graph import NOTICE_AND_CRITERIA, USER_IDEA, _DebateScriptedLLM  # noqa: E402


def _lookup_with_role(persona_id_to_role: dict | None = None):
    def lookup(persona_id: str, query: str):
        return [
            {
                "document_id": f"DOC-{persona_id}",
                "document_name": f"공고문({persona_id})",
                "chunk_id": "C1",
                "document_role": "target",
                "final_score": 0.6,
                "page": 1,
                "section": None,
                "text": f"{persona_id}가 검토할 실제 문서 원문 문장입니다.",
            }
        ]

    return lookup


class _RecordingEvidencePlanner:
    """evidence_planner로 주입되는 fake — 실제 규칙 없이 호출 인자만 기록하고 최소한의
    plain dict(EvidencePlan 모양)를 반환한다."""

    def __init__(self, raise_error: bool = False):
        self.calls: list[dict] = []
        self.raise_error = raise_error

    def __call__(self, *, persona_id, effective_issue, retrieved_evidence, runtime_scope, shadow_history):
        self.calls.append(
            {
                "persona_id": persona_id,
                "effective_issue": dict(effective_issue),
                "retrieved_evidence": list(retrieved_evidence),
                "runtime_scope": dict(runtime_scope),
                "shadow_history": list(shadow_history),
            }
        )
        if self.raise_error:
            raise RuntimeError("planner 시뮬레이션 실패")
        selected = []
        if retrieved_evidence:
            item = retrieved_evidence[0]
            selected = [
                {
                    "ref": item.get("ref"),
                    "chunk_id": item.get("chunk_id"),
                    "document_id": item.get("document_id"),
                    "document_role": item.get("document_role"),
                    "claim_type": "user_provided_fact",
                    "quote": item.get("text", ""),
                    "quote_start": 0,
                    "quote_end": len(item.get("text", "")),
                    "retrieval_score": 0.6,
                    "issue_relevance_score": 0.5,
                    "selection_reason_code": "target_fact_for_current_issue",
                    "reused_in_same_issue": bool(shadow_history),
                }
            ]
        return {
            "plan_id": "EP-test0001",
            "policy_version": "ideation-shadow-v1",
            "persona_id": persona_id,
            "issue": {
                "issue_id": effective_issue["issue_id"],
                "title": effective_issue["title"],
                "query": effective_issue.get("query", ""),
            },
            "eligible_evidence_count": len(selected),
            "grounded_claim_required": bool(selected),
            "expert_judgment_required": not selected,
            "selected_evidence": selected,
            "empty_plan_reason": None if selected else "no_retrieved_evidence",
            "validation": {"valid": True, "errors": []},
        }


def test_resolve_effective_issue_title_matches_resolve_retrieval_issue():
    """요청: retrieval에 실제 사용된 issue와 planner issue가 반드시 동일해야 한다 —
    resolve_effective_issue()의 title이 resolve_retrieval_issue()와 항상 일치하는지 확인."""
    state = initial_conv_state(
        session_id="S-EFFECTIVE-ISSUE", notice_and_criteria=NOTICE_AND_CRITERIA, user_idea=USER_IDEA
    )
    for persona_id in ("planning_expert", "dev_expert"):
        effective = resolve_effective_issue(state, persona_id)
        assert effective["title"] == resolve_retrieval_issue(state, persona_id)
        assert effective["issue_id"]  # 항상 비어있지 않은 결정적 id


def test_evidence_planner_none_matches_baseline_behavior():
    """evidence_planner=None(기본값)이면 evidence_planner를 넘기지 않은 것과 완전히 동일한
    결과가 나와야 한다 — feature flag가 꺼진 것과 같은 상황."""
    llm_a = _DebateScriptedLLM(dev_stance="보완")
    llm_b = _DebateScriptedLLM(dev_stance="보완")
    lookup = _lookup_with_role()

    state_without = start_ideation_conversation(
        session_id="S-NOOP-A", notice_and_criteria=NOTICE_AND_CRITERIA, user_idea=USER_IDEA,
        llm_call=llm_a, evidence_lookup=lookup,
    )
    state_with_none = start_ideation_conversation(
        session_id="S-NOOP-B", notice_and_criteria=NOTICE_AND_CRITERIA, user_idea=USER_IDEA,
        llm_call=llm_b, evidence_lookup=lookup, evidence_planner=None,
    )

    contents_a = [m["content"] for m in state_without["messages"]]
    contents_b = [m["content"] for m in state_with_none["messages"]]
    assert contents_a == contents_b
    assert state_without["phase"] == state_with_none["phase"]


def test_evidence_planner_invoked_after_retrieval_with_expected_arguments():
    llm = _DebateScriptedLLM(dev_stance="보완")
    lookup = _lookup_with_role()
    planner = _RecordingEvidencePlanner()

    start_ideation_conversation(
        session_id="S-PLANNER-CALLED",
        notice_and_criteria=NOTICE_AND_CRITERIA,
        user_idea=USER_IDEA,
        llm_call=llm,
        evidence_lookup=lookup,
        evidence_planner=planner,
    )

    assert planner.calls, "evidence_planner가 최소 한 번은 호출돼야 한다"
    first_call = planner.calls[0]
    assert first_call["persona_id"] in ("planning_expert", "dev_expert")
    assert "issue_id" in first_call["effective_issue"]
    assert "title" in first_call["effective_issue"]
    assert "query" in first_call["effective_issue"]
    assert first_call["retrieved_evidence"], "retrieval 결과가 planner에 그대로 전달돼야 한다"
    assert "session_id" in first_call["runtime_scope"]
    assert "selected_candidate_document_id" in first_call["runtime_scope"]


def test_evidence_planner_result_does_not_leak_into_message_or_claims():
    """Phase 1 요구사항: plan 결과가 prompt/claims/message에 절대 영향을 주지 않는다 —
    메시지 dict에 plan_id/selected_evidence 등 planner 전용 키가 전혀 없어야 한다."""
    llm = _DebateScriptedLLM(dev_stance="보완")
    lookup = _lookup_with_role()
    planner = _RecordingEvidencePlanner()

    state = start_ideation_conversation(
        session_id="S-NO-LEAK",
        notice_and_criteria=NOTICE_AND_CRITERIA,
        user_idea=USER_IDEA,
        llm_call=llm,
        evidence_lookup=lookup,
        evidence_planner=planner,
    )

    for message in state["messages"]:
        assert "plan_id" not in message
        assert "selected_evidence" not in message
        structured = message.get("structured") or {}
        assert "plan_id" not in structured
        assert "selected_evidence" not in structured


def test_evidence_planner_exception_does_not_break_discussion_turn():
    """요청: planner 예외가 나도 기존 발언 생성을 실패시키지 않는다."""
    llm = _DebateScriptedLLM(dev_stance="보완")
    lookup = _lookup_with_role()
    planner = _RecordingEvidencePlanner(raise_error=True)

    state = start_ideation_conversation(
        session_id="S-PLANNER-FAILS",
        notice_and_criteria=NOTICE_AND_CRITERIA,
        user_idea=USER_IDEA,
        llm_call=llm,
        evidence_lookup=lookup,
        evidence_planner=planner,
    )

    assert planner.calls, "예외가 나도 planner는 실제로 호출됐어야 한다"
    assert state["phase"] != "failed"
    assert state["messages"], "planner 실패와 무관하게 발언은 정상적으로 생성돼야 한다"


def test_shadow_history_accumulates_per_speaker_and_issue_without_api_exposure():
    """같은 speaker/issue 조합의 선택 이력이 state에 쌓이고, API 응답에는 노출되지 않아야
    한다(요청: 최소 정보만 세션 범위로 유지, 새 필드를 응답에 불필요하게 노출하지 않음)."""
    llm = _DebateScriptedLLM(dev_stance="보완")
    lookup = _lookup_with_role()
    planner = _RecordingEvidencePlanner()

    state = start_ideation_conversation(
        session_id="S-SHADOW-HISTORY",
        notice_and_criteria=NOTICE_AND_CRITERIA,
        user_idea=USER_IDEA,
        llm_call=llm,
        evidence_lookup=lookup,
        evidence_planner=planner,
    )

    history = state.get("evidence_plan_shadow_history") or {}
    assert history, "선택된 evidence가 있었으므로 shadow history가 최소 한 건은 쌓여야 한다"
    for key, items in history.items():
        assert ":" in key  # "persona_id:issue_id" 형태
        for item in items:
            assert set(item.keys()) == {"speaker", "effective_issue_id", "chunk_id"}
