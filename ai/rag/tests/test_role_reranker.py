"""
Unit Tests for ai.rag.role_retrieval.reranker
"""

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
