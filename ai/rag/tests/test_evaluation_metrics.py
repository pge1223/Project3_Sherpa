"""
Unit Tests for ai.rag.evaluation.metrics
(외부 의존성 없는 순수 함수 — 실제 KURE, Chroma 없음)
"""

import pytest

from ai.rag.evaluation.metrics import (
    deduplicate_ranked_ids,
    dcg_at_k,
    hit_rate_at_k,
    mean_reciprocal_rank,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)


class TestDeduplicateRankedIds:
    def test_keeps_first_occurrence_only(self):
        assert deduplicate_ranked_ids(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]

    def test_empty_list(self):
        assert deduplicate_ranked_ids([]) == []


class TestPerfectRetrieval:
    def test_all_metrics_are_one_when_all_relevant_at_top(self):
        ranked = ["c1", "c2", "c3"]
        relevant = {"c1", "c2", "c3"}
        for k in (1, 2, 3):
            assert precision_at_k(ranked, relevant, k) == 1.0
        assert recall_at_k(ranked, relevant, 3) == 1.0
        assert hit_rate_at_k(ranked, relevant, 1) == 1.0
        assert reciprocal_rank(ranked, relevant) == 1.0
        assert ndcg_at_k(ranked, relevant, 3) == pytest.approx(1.0)


class TestReciprocalRank:
    def test_relevant_at_second_position_gives_half(self):
        ranked = ["c_irrelevant", "c_relevant"]
        relevant = {"c_relevant"}
        assert reciprocal_rank(ranked, relevant) == pytest.approx(0.5)

    def test_no_relevant_found_gives_zero(self):
        ranked = ["c_irrelevant_1", "c_irrelevant_2"]
        relevant = {"c_relevant"}
        assert reciprocal_rank(ranked, relevant) == 0.0

    def test_mean_reciprocal_rank_over_cases(self):
        assert mean_reciprocal_rank([1.0, 0.5, 0.0]) == pytest.approx(0.5)

    def test_mean_reciprocal_rank_empty_is_zero(self):
        assert mean_reciprocal_rank([]) == 0.0


class TestEmptyResults:
    def test_no_results_gives_zero_for_all_metrics(self):
        ranked: list[str] = []
        relevant = {"c1"}
        assert precision_at_k(ranked, relevant, 5) == 0.0
        assert recall_at_k(ranked, relevant, 5) == 0.0
        assert hit_rate_at_k(ranked, relevant, 5) == 0.0
        assert reciprocal_rank(ranked, relevant) == 0.0
        assert ndcg_at_k(ranked, relevant, 5) == 0.0


class TestPartialRetrieval:
    def test_precision_and_recall_with_partial_matches(self):
        ranked = ["c1", "c_irrelevant", "c2", "c_irrelevant_2"]
        relevant = {"c1", "c2", "c3"}  # c3는 검색되지 않음

        # top 2: c1(관련), c_irrelevant(무관) -> precision@2 = 1/2
        assert precision_at_k(ranked, relevant, 2) == pytest.approx(0.5)
        # top 2에서 찾은 관련 청크 1개 / 전체 정답 3개
        assert recall_at_k(ranked, relevant, 2) == pytest.approx(1 / 3)

        # top 4: c1, c2 관련 / 4개 중 -> precision@4 = 2/4
        assert precision_at_k(ranked, relevant, 4) == pytest.approx(0.5)
        # top 4에서 찾은 관련 청크 2개 / 전체 정답 3개
        assert recall_at_k(ranked, relevant, 4) == pytest.approx(2 / 3)

    def test_precision_denominator_uses_actual_returned_count_not_k(self):
        # 반환된 결과가 K보다 적으면 분모는 실제 반환 개수여야 한다
        ranked = ["c1"]
        relevant = {"c1", "c2"}
        assert precision_at_k(ranked, relevant, 5) == pytest.approx(1.0)


class TestNdcg:
    def test_ndcg_matches_hand_computed_value(self):
        import math

        ranked = ["c_irrelevant", "c1", "c2"]
        relevant = {"c1", "c2"}
        # DCG@3 = 0/log2(2) + 1/log2(3) + 1/log2(4)
        expected_dcg = 0.0 + (1.0 / math.log2(3)) + (1.0 / math.log2(4))
        # IDCG@3 = ideal ordering(2개 정답을 앞에) = 1/log2(2) + 1/log2(3)
        expected_idcg = (1.0 / math.log2(2)) + (1.0 / math.log2(3))
        expected_ndcg = expected_dcg / expected_idcg

        assert dcg_at_k(ranked, relevant, 3) == pytest.approx(expected_dcg)
        assert ndcg_at_k(ranked, relevant, 3) == pytest.approx(expected_ndcg)

    def test_ndcg_zero_when_no_relevant_ids(self):
        assert ndcg_at_k(["c1", "c2"], set(), 2) == 0.0


class TestDuplicateChunkIds:
    def test_duplicate_chunk_id_keeps_first_rank_only(self):
        ranked = ["c1", "c1", "c2"]
        relevant = {"c1"}
        # c1이 중복 제거 후 1위 하나만 남아야 하므로 reciprocal rank는 1.0
        assert reciprocal_rank(ranked, relevant) == 1.0
        # top_k=2 -> dedup 후 ["c1", "c2"], precision = 1/2
        assert precision_at_k(ranked, relevant, 2) == pytest.approx(0.5)


class TestKValidation:
    @pytest.mark.parametrize("k", [0, -1])
    def test_invalid_k_rejected(self, k):
        with pytest.raises(ValueError):
            precision_at_k(["c1"], {"c1"}, k)
        with pytest.raises(ValueError):
            recall_at_k(["c1"], {"c1"}, k)
        with pytest.raises(ValueError):
            hit_rate_at_k(["c1"], {"c1"}, k)
        with pytest.raises(ValueError):
            ndcg_at_k(["c1"], {"c1"}, k)
        with pytest.raises(ValueError):
            dcg_at_k(["c1"], {"c1"}, k)
