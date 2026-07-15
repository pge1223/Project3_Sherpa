"""
Unit Tests for ai.rag.role_retrieval.query_builder
"""

from ai.rag.role_retrieval.query_builder import build_expanded_query
from ai.rag.role_retrieval.roles import DEFAULT_ROLE_PROFILES

_QUESTION = "이 사업의 위험 요소는 무엇인가요?"


class TestBuildExpandedQuery:
    def test_finance_role_query(self):
        role = DEFAULT_ROLE_PROFILES["finance"]
        expanded = build_expanded_query(_QUESTION, role)
        assert role.query_instruction in expanded
        assert _QUESTION in expanded

    def test_technology_role_query(self):
        role = DEFAULT_ROLE_PROFILES["technology"]
        expanded = build_expanded_query(_QUESTION, role)
        assert role.query_instruction in expanded
        assert _QUESTION in expanded

    def test_marketing_role_query(self):
        role = DEFAULT_ROLE_PROFILES["marketing"]
        expanded = build_expanded_query(_QUESTION, role)
        assert role.query_instruction in expanded
        assert _QUESTION in expanded

    def test_planning_role_query(self):
        role = DEFAULT_ROLE_PROFILES["planning"]
        expanded = build_expanded_query(_QUESTION, role)
        assert role.query_instruction in expanded
        assert _QUESTION in expanded

    def test_original_question_preserved_across_all_roles(self):
        for role in DEFAULT_ROLE_PROFILES.values():
            expanded = build_expanded_query(_QUESTION, role)
            assert _QUESTION in expanded

    def test_none_role_returns_original_query_unchanged(self):
        assert build_expanded_query(_QUESTION, None) == _QUESTION

    def test_different_roles_produce_different_queries(self):
        finance_query = build_expanded_query(_QUESTION, DEFAULT_ROLE_PROFILES["finance"])
        technology_query = build_expanded_query(_QUESTION, DEFAULT_ROLE_PROFILES["technology"])
        assert finance_query != technology_query
