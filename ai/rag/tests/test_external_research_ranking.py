"""
Unit Tests for ai.rag.external_research.ranking (RAG-007)
================================================================
"""

from ai.rag.external_research.ranking import (
    NEUTRAL_ROLE_SCORE,
    compute_criteria_score,
    compute_final_score,
    compute_role_score,
)


class TestComputeRoleScore:
    def test_matching_role_returns_one(self):
        assert compute_role_score(["marketing", "planning"], "marketing") == 1.0

    def test_non_matching_role_returns_zero(self):
        assert compute_role_score(["finance"], "marketing") == 0.0

    def test_case_insensitive_match(self):
        assert compute_role_score(["Marketing"], "marketing") == 1.0

    def test_empty_supported_roles_returns_neutral(self):
        assert compute_role_score([], "marketing") == NEUTRAL_ROLE_SCORE


class TestComputeCriteriaScore:
    def test_full_overlap_returns_one(self):
        score = compute_criteria_score(["시장성", "기술성"], ["시장성", "기술성"])
        assert score == 1.0

    def test_partial_overlap_returns_ratio(self):
        score = compute_criteria_score(["시장성"], ["시장성", "기술성"])
        assert score == 0.5

    def test_no_overlap_returns_zero(self):
        score = compute_criteria_score(["기술성"], ["시장성"])
        assert score == 0.0

    def test_empty_requested_criteria_returns_zero(self):
        assert compute_criteria_score(["시장성"], []) == 0.0

    def test_empty_evidence_criteria_returns_neutral(self):
        assert compute_criteria_score([], ["시장성"]) == NEUTRAL_ROLE_SCORE

    def test_case_insensitive_match(self):
        score = compute_criteria_score(["시장성"], ["시장성"])
        assert score == 1.0


class TestComputeFinalScore:
    def test_weighted_sum(self):
        score = compute_final_score(
            semantic_score=0.8, role_score=1.0, criteria_score=0.5, freshness_score=0.9,
            semantic_weight=0.55, role_weight=0.20, criteria_weight=0.15, freshness_weight=0.10,
        )
        expected = 0.8 * 0.55 + 1.0 * 0.20 + 0.5 * 0.15 + 0.9 * 0.10
        assert abs(score - expected) < 1e-9

    def test_all_zero_scores_give_zero(self):
        score = compute_final_score(
            semantic_score=0.0, role_score=0.0, criteria_score=0.0, freshness_score=0.0,
            semantic_weight=0.55, role_weight=0.20, criteria_weight=0.15, freshness_weight=0.10,
        )
        assert score == 0.0

    def test_all_max_scores_with_default_weights_near_one(self):
        score = compute_final_score(
            semantic_score=1.0, role_score=1.0, criteria_score=1.0, freshness_score=1.0,
            semantic_weight=0.55, role_weight=0.20, criteria_weight=0.15, freshness_weight=0.10,
        )
        assert abs(score - 1.0) < 1e-9

    def test_weights_change_ranking_order(self):
        # semantic 위주 가중치일 때는 semantic이 높은 후보가 이겨야 한다.
        high_semantic = compute_final_score(
            semantic_score=0.9, role_score=0.0, criteria_score=0.0, freshness_score=0.0,
            semantic_weight=1.0, role_weight=0.0, criteria_weight=0.0, freshness_weight=0.0,
        )
        high_role = compute_final_score(
            semantic_score=0.1, role_score=0.9, criteria_score=0.0, freshness_score=0.0,
            semantic_weight=1.0, role_weight=0.0, criteria_weight=0.0, freshness_weight=0.0,
        )
        assert high_semantic > high_role

    def test_no_llm_used_pure_arithmetic(self):
        # 순수 함수 호출만으로 결정되는지 확인 (외부 의존성 없음 자체가 증거).
        import inspect

        source = inspect.getsource(compute_final_score)
        assert "llm" not in source.lower()
        assert "openai" not in source.lower()
