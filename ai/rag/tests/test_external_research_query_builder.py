"""
Unit Tests for ai.rag.external_research.query_builder (RAG-007)
======================================================================
"""

from ai.rag.external_research.query_builder import (
    ROLE_QUERY_TERMS,
    build_external_research_query,
    get_role_query_terms,
)
from ai.rag.external_research.schemas import ExternalEvidenceType


class TestGetRoleQueryTerms:
    def test_known_role_returns_terms(self):
        terms = get_role_query_terms("marketing")
        assert "시장 규모" in terms

    def test_unknown_role_returns_empty_list_not_error(self):
        assert get_role_query_terms("unknown_role") == []

    def test_all_documented_roles_present(self):
        for role in ("marketing", "planning", "finance", "technology"):
            assert role in ROLE_QUERY_TERMS


class TestBuildExternalResearchQuery:
    def test_domain_reflected(self):
        query = build_external_research_query(
            domain="공공 AI 서비스", evaluation_criteria=["시장성"], reviewer_role="planning"
        )
        assert "공공 AI 서비스" in query

    def test_evaluation_criteria_reflected(self):
        query = build_external_research_query(
            domain="d", evaluation_criteria=["시장성", "정책 적합성"], reviewer_role="planning"
        )
        assert "시장성, 정책 적합성" in query

    def test_reviewer_role_reflected(self):
        query = build_external_research_query(domain="d", evaluation_criteria=["c"], reviewer_role="finance")
        assert "finance" in query

    def test_role_expansion_terms_applied(self):
        query = build_external_research_query(domain="d", evaluation_criteria=["c"], reviewer_role="marketing")
        assert "시장 규모" in query
        assert "경쟁 현황" in query

    def test_unknown_role_no_expansion_terms_but_no_error(self):
        query = build_external_research_query(domain="d", evaluation_criteria=["c"], reviewer_role="unknown")
        assert "역할별 관심 주제" not in query

    def test_region_reflected(self):
        query = build_external_research_query(
            domain="d", evaluation_criteria=["c"], reviewer_role="planning", region="대한민국"
        )
        assert "대한민국" in query

    def test_query_context_reflected(self):
        query = build_external_research_query(
            domain="d",
            evaluation_criteria=["c"],
            reviewer_role="planning",
            query_context="공공기관 사업계획서 자동 평가 서비스",
        )
        assert "공공기관 사업계획서 자동 평가 서비스" in query

    def test_evidence_types_reflected(self):
        query = build_external_research_query(
            domain="d",
            evaluation_criteria=["c"],
            reviewer_role="planning",
            evidence_types=[ExternalEvidenceType.STATISTICS, ExternalEvidenceType.POLICY],
        )
        assert "statistics" in query
        assert "policy" in query

    def test_same_input_produces_same_query(self):
        kwargs = dict(
            domain="d", evaluation_criteria=["c1", "c2"], reviewer_role="technology",
            query_context="ctx", region="r",
        )
        assert build_external_research_query(**kwargs) == build_external_research_query(**kwargs)

    def test_does_not_fabricate_sources_or_statistics(self):
        query = build_external_research_query(domain="d", evaluation_criteria=["c"], reviewer_role="finance")
        # 순수 문자열 조합이므로 입력에 없던 URL이나 숫자가 새로 생기지 않는다.
        assert "http" not in query
        assert not any(char.isdigit() for char in query)

    def test_no_query_context_omits_section(self):
        query = build_external_research_query(domain="d", evaluation_criteria=["c"], reviewer_role="planning")
        assert "검색 문맥" not in query
