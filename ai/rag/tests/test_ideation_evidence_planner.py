"""
Ideation Evidence Planner Tests (Phase 1 — Shadow Deterministic Evidence Planner)
======================================================================================
용준/Claude(2026-07-23). ai/rag/orchestration/ideation_evidence_planner.py의 결정적 규칙
(eligibility/quote 추출/plan validation/build_evidence_plan)을 검증한다. Phase 1은
prompt/claims/grounding/routing에 영향을 주지 않는 shadow 모듈이므로, 이 테스트는 API 응답이나
LLM 호출과 무관하게 순수 함수 단위로만 확인한다.
"""

from ai.rag.evidence_linking.config import EvidenceLinkingConfig
from ai.rag.orchestration.ideation_evidence_planner import (
    build_evidence_plan,
    evaluate_evidence_eligibility,
    extract_planner_quote,
    resolve_retrieval_score,
    validate_evidence_plan,
)

_ISSUE = {
    "issue_id": "differentiation",
    "title": "차별성과 고객 가치",
    "query": "차별성과 고객 가치 실현 가능성",
}


def _target_item(ref="E1", chunk_id="chk_target_1", score=0.6, text=None) -> dict:
    return {
        "ref": ref,
        "chunk_id": chunk_id,
        "document_id": "DOC-target-1",
        "document_role": "target",
        "final_score": score,
        "text": text or "우리 서비스는 차별성과 고객 가치를 갖춘 실현 가능성이 높은 방식입니다.",
    }


def _criteria_item(ref="E2", chunk_id="chk_criteria_1", score=0.55, text=None) -> dict:
    return {
        "ref": ref,
        "chunk_id": chunk_id,
        "document_id": "DOC-criteria-1",
        "document_role": "criteria",
        "final_score": score,
        "text": text or "평가 기준은 차별성과 고객 가치, 실현 가능성을 중점적으로 심사합니다.",
    }


class TestResolveRetrievalScore:
    def test_prefers_final_score(self):
        score, reason = resolve_retrieval_score({"final_score": 0.7, "semantic_score": 0.1, "score": 0.2})
        assert score == 0.7
        assert reason is None

    def test_falls_back_to_semantic_then_score(self):
        assert resolve_retrieval_score({"semantic_score": 0.4, "score": 0.2}) == (0.4, None)
        assert resolve_retrieval_score({"score": 0.2}) == (0.2, None)

    def test_missing_all_scores(self):
        score, reason = resolve_retrieval_score({})
        assert score is None
        assert reason == "missing_retrieval_score"


class TestEvaluateEvidenceEligibility:
    def test_eligible_target_passes_all_gates(self):
        result = evaluate_evidence_eligibility(
            _target_item(), persona_id="planning_expert", effective_issue=_ISSUE, runtime_scope={}
        )
        assert result["eligible"] is True
        assert result["structural_valid"] is True
        assert result["scope_valid"] is True
        assert result["retrieval_score_pass"] is True
        assert result["role_policy_pass"] is True
        assert result["exclusion_reasons"] == []

    def test_structurally_invalid_missing_chunk_id(self):
        item = _target_item()
        del item["chunk_id"]
        result = evaluate_evidence_eligibility(
            item, persona_id="planning_expert", effective_issue=_ISSUE, runtime_scope={}
        )
        assert result["eligible"] is False
        assert "structurally_invalid" in result["exclusion_reasons"]

    def test_below_retrieval_score_excluded(self):
        item = _target_item(score=0.05)
        result = evaluate_evidence_eligibility(
            item, persona_id="planning_expert", effective_issue=_ISSUE, runtime_scope={}
        )
        assert result["eligible"] is False
        assert "below_retrieval_score" in result["exclusion_reasons"]

    def test_missing_retrieval_score_excluded(self):
        item = _target_item()
        del item["final_score"]
        result = evaluate_evidence_eligibility(
            item, persona_id="planning_expert", effective_issue=_ISSUE, runtime_scope={}
        )
        assert result["eligible"] is False
        assert "missing_retrieval_score" in result["exclusion_reasons"]

    def test_unsupported_document_role_excluded(self):
        item = _target_item()
        item["document_role"] = "similar_case"
        result = evaluate_evidence_eligibility(
            item, persona_id="planning_expert", effective_issue=_ISSUE, runtime_scope={}
        )
        assert result["eligible"] is False
        assert "unsupported_document_role" in result["exclusion_reasons"]

    def test_criteria_excluded_when_issue_not_relevant(self):
        item = _criteria_item()
        irrelevant_issue = {"issue_id": "mvp", "title": "MVP 범위", "query": "MVP 범위 핵심 기능"}
        result = evaluate_evidence_eligibility(
            item, persona_id="planning_expert", effective_issue=irrelevant_issue, runtime_scope={}
        )
        assert result["eligible"] is False
        assert "criteria_not_relevant_to_issue" in result["exclusion_reasons"]

    def test_criteria_allowed_when_issue_relevant_for_dev(self):
        item = _criteria_item(text="본 사업은 기술 실현 가능성과 데이터 확보 방안을 중점 평가합니다.")
        issue = {"issue_id": "mvp", "title": "MVP 범위", "query": "MVP 범위와 기술 실현 가능성"}
        result = evaluate_evidence_eligibility(
            item, persona_id="dev_expert", effective_issue=issue, runtime_scope={}
        )
        assert result["role_policy_pass"] is True

    def test_planning_criteria_allowed_for_problem_definition(self):
        item = _criteria_item(text="도시 문제의 설정이 구체적인지와 AI 기반 해결 목표 및 KPI를 평가합니다.")
        issue = {
            "issue_id": "problem",
            "title": "문제 정의",
            "query": "도시 교통 혼잡 문제 정의와 AI 해결 목표 KPI",
        }
        result = evaluate_evidence_eligibility(
            item, persona_id="planning_expert", effective_issue=issue, runtime_scope={}
        )
        assert result["role_policy_pass"] is True
        assert result["issue_relevance_score"] >= 0.15
        assert result["eligible"] is True

    def test_planning_criteria_allowed_for_data_integration_strategy(self):
        item = _criteria_item(text="데이터와 디지털 기술이 도시 운영에 효과적으로 활용되었는지 평가합니다.")
        issue = {
            "issue_id": "data_integration",
            "title": "데이터 통합 전략",
            "query": "공공 교통 데이터 통합 전략과 도시 운영 활용",
        }
        result = evaluate_evidence_eligibility(
            item, persona_id="planning_expert", effective_issue=issue, runtime_scope={}
        )
        assert result["role_policy_pass"] is True
        assert result["issue_relevance_score"] >= 0.15
        assert result["eligible"] is True

    def test_dev_criteria_allowed_for_problem_definition(self):
        item = _criteria_item(text="AI 기술이 실제 도시 문제 해결에 적용 가능한지 평가합니다.")
        issue = {
            "issue_id": "problem_definition",
            "title": "문제 정의",
            "query": "도시 교통 혼잡 문제와 AI 적용 가능성",
        }
        result = evaluate_evidence_eligibility(
            item, persona_id="dev_expert", effective_issue=issue, runtime_scope={}
        )
        assert result["role_policy_pass"] is True
        assert result["issue_relevance_pass"] is True
        assert result["eligible"] is True

    def test_expanded_planning_policy_still_rejects_issue_irrelevant_criteria(self):
        item = _criteria_item(text="조리법과 식자재 보관 방법을 설명하는 문서입니다.")
        issue = {
            "issue_id": "problem",
            "title": "문제 정의",
            "query": "도시 교통 혼잡 문제와 사용자 피해",
        }
        result = evaluate_evidence_eligibility(
            item, persona_id="planning_expert", effective_issue=issue, runtime_scope={}
        )
        assert result["role_policy_pass"] is True
        assert result["issue_relevance_pass"] is False
        assert result["eligible"] is False
        assert "below_issue_relevance" in result["exclusion_reasons"]

    def test_candidate_scope_mismatch_excluded(self):
        item = _target_item()
        item["ideation_source_type"] = "ideation_candidate"
        item["document_id"] = "DOC-other-candidate"
        result = evaluate_evidence_eligibility(
            item,
            persona_id="planning_expert",
            effective_issue=_ISSUE,
            runtime_scope={"selected_candidate_document_id": "DOC-target-1"},
        )
        assert result["scope_valid"] is False
        assert "candidate_scope_mismatch" in result["exclusion_reasons"]

    def test_user_session_answer_scope_valid_when_session_matches(self):
        item = _target_item()
        item["ideation_source_type"] = "user_session_answer"
        item["session_id"] = "SESSION-1"
        result = evaluate_evidence_eligibility(
            item,
            persona_id="planning_expert",
            effective_issue=_ISSUE,
            runtime_scope={"session_id": "SESSION-1"},
        )
        assert result["scope_valid"] is True

    def test_session_scope_mismatch_excluded(self):
        item = _target_item()
        item["ideation_source_type"] = "user_session_answer"
        item["session_id"] = "SESSION-OTHER"
        result = evaluate_evidence_eligibility(
            item,
            persona_id="planning_expert",
            effective_issue=_ISSUE,
            runtime_scope={"session_id": "SESSION-1"},
        )
        assert result["scope_valid"] is False
        assert "session_scope_mismatch" in result["exclusion_reasons"]

    def test_below_issue_relevance_excluded(self):
        item = _target_item(text="이 문단은 완전히 다른 주제인 조리법과 식자재 보관 방법을 설명합니다.")
        result = evaluate_evidence_eligibility(
            item, persona_id="planning_expert", effective_issue=_ISSUE, runtime_scope={}
        )
        assert result["eligible"] is False
        assert "below_issue_relevance" in result["exclusion_reasons"]

    def test_custom_config_min_evidence_score_respected(self):
        item = _target_item(score=0.35)
        cfg = EvidenceLinkingConfig(min_evidence_score=0.5)
        result = evaluate_evidence_eligibility(
            item, persona_id="planning_expert", effective_issue=_ISSUE, runtime_scope={}, config=cfg
        )
        assert result["retrieval_score_pass"] is False


class TestExtractPlannerQuote:
    def test_exact_substring_invariant(self):
        content = "이 서비스는 차별성과 고객 가치를 제공합니다. 그리고 다른 문장도 있습니다."
        result = extract_planner_quote(content, "차별성과 고객 가치")
        assert result is not None
        quote, start, end = result
        assert content[start:end] == quote

    def test_returns_none_when_no_keyword_overlap(self):
        content = "완전히 무관한 내용의 문장입니다."
        assert extract_planner_quote(content, "차별성과 고객 가치") is None

    def test_returns_none_for_empty_content(self):
        assert extract_planner_quote("", "질문") is None

    def test_splits_on_newline_and_bullet(self):
        content = "- 차별성: 고객 가치 중심 설계\n- 무관한 다른 항목 설명"
        result = extract_planner_quote(content, "차별성 고객 가치")
        assert result is not None
        quote, start, end = result
        assert content[start:end] == quote
        assert quote.startswith("차별성")

    def test_prefers_earliest_span_on_tie(self):
        content = "차별성 문장 하나. 차별성 문장 둘."
        result = extract_planner_quote(content, "차별성")
        assert result is not None
        _, start, _ = result
        assert start == 0

    def test_no_ellipsis_added(self):
        content = "차별성과 고객 가치가 핵심입니다."
        result = extract_planner_quote(content, "차별성과 고객 가치")
        assert result is not None
        quote, _, _ = result
        assert "…" not in quote
        assert quote in content


class TestValidateEvidencePlan:
    def _valid_selected(self, item):
        return {
            "ref": item["ref"],
            "chunk_id": item["chunk_id"],
            "document_id": item["document_id"],
            "document_role": item["document_role"],
            "claim_type": "user_provided_fact" if item["document_role"] == "target" else "document_fact",
            "quote": item["text"],
            "quote_start": 0,
            "quote_end": len(item["text"]),
            "retrieval_score": 0.6,
            "issue_relevance_score": 0.5,
            "selection_reason_code": "target_fact_for_current_issue",
            "reused_in_same_issue": False,
        }

    def test_valid_plan_passes(self):
        item = _target_item()
        plan = {"selected_evidence": [self._valid_selected(item)]}
        result = validate_evidence_plan(plan, retrieved_evidence=[item], runtime_scope={})
        assert result == {"valid": True, "errors": []}

    def test_unknown_ref_fails(self):
        item = _target_item()
        selected = self._valid_selected(item)
        selected["ref"] = "E999"
        plan = {"selected_evidence": [selected]}
        result = validate_evidence_plan(plan, retrieved_evidence=[item], runtime_scope={})
        assert result["valid"] is False
        assert any(e.startswith("unknown_ref:") for e in result["errors"])

    def test_quote_offset_invariant_failure(self):
        item = _target_item()
        selected = self._valid_selected(item)
        selected["quote_start"] = 0
        selected["quote_end"] = 3
        selected["quote"] = "완전히 다른 문자열"
        plan = {"selected_evidence": [selected]}
        result = validate_evidence_plan(plan, retrieved_evidence=[item], runtime_scope={})
        assert result["valid"] is False
        assert any(e.startswith("quote_offset_invariant_failed:") for e in result["errors"])

    def test_duplicate_ref_fails(self):
        item = _target_item()
        selected = self._valid_selected(item)
        plan = {"selected_evidence": [selected, dict(selected)]}
        result = validate_evidence_plan(plan, retrieved_evidence=[item], runtime_scope={})
        assert result["valid"] is False
        assert any(e.startswith("duplicate_ref:") for e in result["errors"])

    def test_scope_violation_detected(self):
        item = _target_item()
        item["ideation_source_type"] = "ideation_candidate"
        selected = self._valid_selected(item)
        plan = {"selected_evidence": [selected]}
        result = validate_evidence_plan(
            plan, retrieved_evidence=[item], runtime_scope={"selected_candidate_document_id": "DOC-other"}
        )
        assert result["valid"] is False
        assert any(e.startswith("scope_violation:") for e in result["errors"])

    def test_claim_type_mismatch_detected(self):
        item = _target_item()
        selected = self._valid_selected(item)
        selected["claim_type"] = "document_fact"  # target should be user_provided_fact
        plan = {"selected_evidence": [selected]}
        result = validate_evidence_plan(plan, retrieved_evidence=[item], runtime_scope={})
        assert result["valid"] is False
        assert any(e.startswith("claim_type_mismatch:") for e in result["errors"])


class TestBuildEvidencePlan:
    def test_no_retrieved_evidence_returns_empty_plan(self):
        plan = build_evidence_plan(
            persona_id="planning_expert", effective_issue=_ISSUE, retrieved_evidence=[], runtime_scope={}, shadow_history=[]
        )
        assert plan["empty_plan_reason"] == "no_retrieved_evidence"
        assert plan["selected_evidence"] == []
        assert plan["validation"]["valid"] is True

    def test_selects_target_and_criteria_with_correct_claim_type(self):
        items = [_target_item(), _criteria_item()]
        plan = build_evidence_plan(
            persona_id="planning_expert",
            effective_issue=_ISSUE,
            retrieved_evidence=items,
            runtime_scope={},
            shadow_history=[],
        )
        assert plan["empty_plan_reason"] is None
        assert plan["validation"]["valid"] is True
        roles = {e["document_role"]: e for e in plan["selected_evidence"]}
        assert roles["target"]["claim_type"] == "user_provided_fact"
        assert roles["criteria"]["claim_type"] == "document_fact"
        assert len(plan["selected_evidence"]) == 2

    def test_role_max_one_each_even_with_multiple_candidates(self):
        items = [
            _target_item(ref="E1", chunk_id="chk_t1"),
            _target_item(ref="E2", chunk_id="chk_t2"),
            _criteria_item(ref="E3", chunk_id="chk_c1"),
        ]
        plan = build_evidence_plan(
            persona_id="planning_expert",
            effective_issue=_ISSUE,
            retrieved_evidence=items,
            runtime_scope={},
            shadow_history=[],
        )
        target_selected = [e for e in plan["selected_evidence"] if e["document_role"] == "target"]
        assert len(target_selected) == 1

    def test_role_policy_excluded_all_when_only_irrelevant_criteria(self):
        irrelevant_issue = {"issue_id": "roadmap", "title": "확장 로드맵", "query": "확장 로드맵 향후 계획"}
        items = [_criteria_item(text="평가 기준은 차별성과 고객 가치, 실현 가능성을 중점적으로 심사합니다.")]
        plan = build_evidence_plan(
            persona_id="planning_expert",
            effective_issue=irrelevant_issue,
            retrieved_evidence=items,
            runtime_scope={},
            shadow_history=[],
        )
        assert plan["empty_plan_reason"] == "role_policy_excluded_all"
        assert plan["selected_evidence"] == []

    def test_reused_in_same_issue_flagged_from_shadow_history(self):
        item = _target_item(chunk_id="chk_target_reused")
        history = [{"speaker": "planning_expert", "effective_issue_id": "differentiation", "chunk_id": "chk_target_reused"}]
        plan = build_evidence_plan(
            persona_id="planning_expert",
            effective_issue=_ISSUE,
            retrieved_evidence=[item],
            runtime_scope={},
            shadow_history=history,
        )
        selected = plan["selected_evidence"][0]
        assert selected["reused_in_same_issue"] is True
        assert selected["selection_reason_code"].endswith("_reused")

    def test_only_unique_eligible_evidence_not_dropped_even_if_reused(self):
        item = _target_item(chunk_id="chk_only_option")
        history = [{"speaker": "planning_expert", "effective_issue_id": "differentiation", "chunk_id": "chk_only_option"}]
        plan = build_evidence_plan(
            persona_id="planning_expert",
            effective_issue=_ISSUE,
            retrieved_evidence=[item],
            runtime_scope={},
            shadow_history=history,
        )
        assert len(plan["selected_evidence"]) == 1
        assert plan["selected_evidence"][0]["reused_in_same_issue"] is True

    def test_plan_id_and_policy_version_present(self):
        plan = build_evidence_plan(
            persona_id="planning_expert",
            effective_issue=_ISSUE,
            retrieved_evidence=[_target_item()],
            runtime_scope={},
            shadow_history=[],
        )
        assert plan["plan_id"].startswith("EP-")
        assert plan["policy_version"] == "ideation-planner-v3"
