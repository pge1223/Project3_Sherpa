"""
Unit Tests for ai.rag.role_retrieval.reranker
"""

import pytest
from pydantic import ValidationError

from ai.rag.retrieval.schemas import SearchResult
from ai.rag.role_retrieval.config import RoleRerankConfig
from ai.rag.role_retrieval.reranker import combine_scores, compute_role_score, rerank_by_role
from ai.rag.role_retrieval.roles import DEFAULT_ROLE_PROFILES

_FINANCE = DEFAULT_ROLE_PROFILES["finance"]
_TECHNOLOGY = DEFAULT_ROLE_PROFILES["technology"]


def _make_result(record_id: str, content: str, score, section_title=None, document_title=None) -> SearchResult:
    return SearchResult(
        record_id=record_id,
        chunk_id=record_id,
        document_id="doc-1",
        content=content,
        distance=None if score is None else 1.0 - score,
        score=score,
        metadata={
            "section_title": section_title,
            "document_title": document_title,
            "content_kind": "body",
        },
    )


class TestComputeRoleScore:
    def test_none_role_profile_gives_zero_score(self):
        result = _make_result("r1", "예산과 비용에 대한 설명", score=0.5)
        assert compute_role_score(result, None, RoleRerankConfig()) == 0.0

    def test_content_keyword_increases_role_score(self):
        with_keyword = _make_result("r1", "이 사업의 예산과 자금조달 계획은 다음과 같다.", score=0.5)
        without_keyword = _make_result("r2", "이 사업의 목표 고객은 20대 여성이다.", score=0.5)
        with_score = compute_role_score(with_keyword, _FINANCE, RoleRerankConfig())
        without_score = compute_role_score(without_keyword, _FINANCE, RoleRerankConfig())
        assert with_score > without_score

    def test_section_title_keyword_increases_role_score_more_than_content(self):
        section_hit = _make_result("r1", "일반 설명 텍스트", score=0.5, section_title="예산 및 비용 계획")
        content_hit = _make_result("r2", "예산 이야기가 살짝 나온다", score=0.5, section_title="일반 개요")
        section_score = compute_role_score(section_hit, _FINANCE, RoleRerankConfig())
        content_score = compute_role_score(content_hit, _FINANCE, RoleRerankConfig())
        assert section_score > content_score

    def test_role_score_is_capped(self):
        spammy = _make_result(
            "r1",
            " ".join(_FINANCE.focus_keywords * 10),
            score=0.5,
            section_title=" ".join(_FINANCE.section_keywords * 10),
            document_title=" ".join(_FINANCE.focus_keywords * 10),
        )
        config = RoleRerankConfig()
        score = compute_role_score(spammy, _FINANCE, config)
        assert score <= config.max_role_score


class TestCombineScores:
    def test_semantic_and_role_score_combined_with_weights(self):
        config = RoleRerankConfig(semantic_weight=0.75, role_weight=0.25)
        final = combine_scores(semantic_score=0.8, role_score=0.4, config=config)
        assert final == 0.8 * 0.75 + 0.4 * 0.25

    def test_none_semantic_score_treated_as_zero(self):
        config = RoleRerankConfig()
        final = combine_scores(semantic_score=None, role_score=0.5, config=config)
        assert final == 0.5 * config.role_weight


class TestRerankByRole:
    def test_results_sorted_by_final_score_descending(self):
        candidates = [
            _make_result("r1", "관련 없는 내용", score=0.9),
            _make_result("r2", "예산과 비용, 자금조달, 재무 위험 설명", score=0.5, section_title="예산 계획"),
        ]
        reranked = rerank_by_role(candidates, _FINANCE, "finance", RoleRerankConfig(), top_k=5)
        scores = [r.final_score for r in reranked]
        assert scores == sorted(scores, reverse=True)

    def test_top_k_limits_result_count(self):
        candidates = [_make_result(f"r{i}", f"content {i}", score=0.5) for i in range(10)]
        reranked = rerank_by_role(candidates, None, None, RoleRerankConfig(), top_k=3)
        assert len(reranked) == 3

    def test_original_content_and_metadata_preserved(self):
        candidates = [_make_result("r1", "원본 내용 그대로", score=0.5, section_title="개요")]
        reranked = rerank_by_role(candidates, _FINANCE, "finance", RoleRerankConfig(), top_k=5)
        assert reranked[0].content == "원본 내용 그대로"
        assert reranked[0].metadata["section_title"] == "개요"

    def test_no_embedding_vector_in_result(self):
        candidates = [_make_result("r1", "내용", score=0.5)]
        reranked = rerank_by_role(candidates, _FINANCE, "finance", RoleRerankConfig(), top_k=5)
        dumped = reranked[0].model_dump()
        assert "embedding" not in dumped
        assert "embedding_text" not in dumped

    def test_same_candidates_different_role_produce_different_order(self):
        candidates = [
            _make_result("r1", "예산과 자금조달, 재무 위험 설명", score=0.5, section_title="예산 계획"),
            _make_result("r2", "기술 구조와 보안, 확장성 설명", score=0.5, section_title="기술 아키텍처"),
        ]
        finance_order = [r.record_id for r in rerank_by_role(candidates, _FINANCE, "finance", RoleRerankConfig(), top_k=5)]
        technology_order = [
            r.record_id for r in rerank_by_role(candidates, _TECHNOLOGY, "technology", RoleRerankConfig(), top_k=5)
        ]
        assert finance_order != technology_order
        assert finance_order[0] == "r1"
        assert technology_order[0] == "r2"


class TestRerankByRoleDeduplication:
    """단일 rerank_by_role() 호출(= search_by_role() 1회 = 하나의 persona/criterion 검색)
    내부에서만 적용되는 중복/과도 중첩 청크 제거."""

    def test_exact_duplicate_chunk_id_is_removed(self):
        candidates = [
            _make_result("r1", "예산과 비용에 대한 설명입니다.", score=0.8),
            _make_result("r1", "예산과 비용에 대한 설명입니다.", score=0.8),
        ]
        reranked = rerank_by_role(candidates, None, None, RoleRerankConfig(), top_k=5)
        assert len(reranked) == 1

    def test_whitespace_only_difference_is_treated_as_duplicate(self):
        candidates = [
            _make_result("r1", "예산과   비용에 대한\n설명입니다.", score=0.9),
            _make_result("r2", "예산과 비용에 대한 설명입니다.", score=0.5),
        ]
        reranked = rerank_by_role(candidates, None, None, RoleRerankConfig(), top_k=5)
        assert len(reranked) == 1
        assert reranked[0].record_id == "r1"  # 점수가 더 높은 쪽이 남음

    def test_overlapping_content_from_chunk_overlap_is_deduplicated(self):
        # chunk_overlap으로 인해 서로 다른 chunk_id지만 단어 대부분이 겹치는 인접 청크
        candidates = [
            _make_result(
                "r1",
                "예산 편성과 사업비 집행 계획은 다음과 같이 산정하였다 세부 내역은 별첨과 같다",
                score=0.9,
            ),
            _make_result(
                "r2",
                "사업비 집행 계획은 다음과 같이 산정하였다 세부 내역은 별첨과 같다 추가로 예비비를 반영하였다",
                score=0.85,
            ),
        ]
        reranked = rerank_by_role(candidates, None, None, RoleRerankConfig(), top_k=5)
        assert len(reranked) == 1
        assert reranked[0].record_id == "r1"

    def test_distinct_content_is_not_deduplicated(self):
        topics = [
            "예산 편성 근거와 산출 방식",
            "기술 아키텍처와 확장성 검토",
            "목표 고객과 시장 규모 분석",
            "정책 목표와 공공성 부합 여부",
            "추진 일정과 마일스톤 계획",
            "위험 대응과 예비비 반영 방안",
            "경쟁사 대비 차별화 전략",
            "인력 구성과 조직 운영 방식",
            "성과 지표와 측정 방법론",
            "지속가능성과 사후 관리 체계",
        ]
        candidates = [_make_result(f"r{i}", topic, score=0.5) for i, topic in enumerate(topics)]
        reranked = rerank_by_role(candidates, None, None, RoleRerankConfig(), top_k=10)
        assert len(reranked) == 10

    def test_different_persona_scope_call_allows_same_evidence(self):
        # 동일 근거(candidate)를 서로 다른 persona 검색(= 별도의 rerank_by_role 호출)에서
        # 각자 쓰는 것은 정상 — 호출 간에는 dedup 상태를 전혀 공유하지 않는다.
        shared_candidates = [_make_result("r1", "정책 목표와 예산 집행이 함께 언급된 근거", score=0.7)]
        first_call = rerank_by_role(shared_candidates, None, None, RoleRerankConfig(), top_k=5)
        second_call = rerank_by_role(shared_candidates, None, None, RoleRerankConfig(), top_k=5)
        assert len(first_call) == 1
        assert len(second_call) == 1
        assert first_call[0].chunk_id == second_call[0].chunk_id == "r1"


class TestRerankByRoleSectionDiversity:
    def test_prefers_different_section_when_scores_are_close(self):
        config = RoleRerankConfig(diversity_score_epsilon=0.1)
        candidates = [
            _make_result("r1", "예산 편성에 대한 설명", score=0.90, section_title="예산"),
            _make_result("r2", "예산 배분에 대한 추가 설명", score=0.88, section_title="예산"),
            _make_result("r3", "집행 일정에 대한 설명", score=0.85, section_title="집행 일정"),
        ]
        reranked = rerank_by_role(candidates, None, None, config, top_k=2)
        sections = [r.metadata.get("section_title") for r in reranked]
        assert "예산" in sections and "집행 일정" in sections


class TestRoleRerankConfigValidation:
    def test_default_duplicate_content_overlap_coefficient_is_in_unit_range(self):
        config = RoleRerankConfig()
        assert 0.0 <= config.duplicate_content_overlap_coefficient <= 1.0

    @pytest.mark.parametrize("value", [0.0, 0.5, 1.0])
    def test_duplicate_content_overlap_coefficient_accepts_boundary_values(self, value):
        assert RoleRerankConfig(duplicate_content_overlap_coefficient=value).duplicate_content_overlap_coefficient == value

    @pytest.mark.parametrize("value", [-0.01, 1.01, -1.0, 2.0])
    def test_duplicate_content_overlap_coefficient_rejects_out_of_range_values(self, value):
        with pytest.raises(ValidationError):
            RoleRerankConfig(duplicate_content_overlap_coefficient=value)

    def test_diversity_score_epsilon_accepts_zero(self):
        assert RoleRerankConfig(diversity_score_epsilon=0.0).diversity_score_epsilon == 0.0

    def test_diversity_score_epsilon_rejects_negative_value(self):
        with pytest.raises(ValidationError):
            RoleRerankConfig(diversity_score_epsilon=-0.01)

    def test_score_order_wins_when_difference_exceeds_epsilon(self):
        config = RoleRerankConfig(diversity_score_epsilon=0.01)
        candidates = [
            _make_result("r1", "가장 관련성 높은 설명", score=0.95, section_title="예산"),
            _make_result("r2", "관련성 낮은 설명", score=0.40, section_title="집행 일정"),
        ]
        reranked = rerank_by_role(candidates, None, None, config, top_k=1)
        assert reranked[0].record_id == "r1"
