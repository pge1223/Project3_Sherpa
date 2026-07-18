"""
Unit Tests for ai.rag.role_retrieval.roles
(순수 함수/데이터 — 실제 Chroma/KURE/LLM/LangGraph 없음)
"""

import pytest

from ai.rag.role_retrieval.roles import DEFAULT_ROLE_PROFILES, RoleRegistry, UnsupportedRoleError


class TestDefaultRoleProfilesRegistered:
    def test_existing_roles_still_registered(self):
        for role_id in ("finance", "technology", "marketing", "planning"):
            assert role_id in DEFAULT_ROLE_PROFILES

    def test_policy_registered(self):
        assert "policy" in DEFAULT_ROLE_PROFILES

    def test_budget_execution_registered(self):
        assert "budget_execution" in DEFAULT_ROLE_PROFILES


class TestPolicyRoleProfile:
    def test_query_instruction_reflects_policy_perspective(self):
        role = DEFAULT_ROLE_PROFILES["policy"]
        assert "정책" in role.query_instruction
        assert "공공성" in role.query_instruction

    def test_focus_keywords_reflect_policy_perspective(self):
        role = DEFAULT_ROLE_PROFILES["policy"]
        assert "정책 목표" in role.focus_keywords
        assert "공공성" in role.focus_keywords
        assert "지원요건" in role.focus_keywords

    def test_section_keywords_reflect_policy_perspective(self):
        role = DEFAULT_ROLE_PROFILES["policy"]
        assert "정책" in role.section_keywords


class TestBudgetExecutionRoleProfile:
    def test_query_instruction_reflects_budget_and_execution_perspective(self):
        role = DEFAULT_ROLE_PROFILES["budget_execution"]
        assert "예산" in role.query_instruction
        assert "집행" in role.query_instruction

    def test_focus_keywords_reflect_budget_and_execution_perspective(self):
        role = DEFAULT_ROLE_PROFILES["budget_execution"]
        assert "예산" in role.focus_keywords
        assert "집행계획" in role.focus_keywords
        assert "마일스톤" in role.focus_keywords

    def test_section_keywords_reflect_budget_and_execution_perspective(self):
        role = DEFAULT_ROLE_PROFILES["budget_execution"]
        assert "예산" in role.section_keywords


class TestRoleRegistryLookup:
    def test_get_returns_profile_for_each_default_role(self):
        registry = RoleRegistry()
        for role_id in DEFAULT_ROLE_PROFILES:
            profile = registry.get(role_id)
            assert profile.role_id == role_id

    def test_has_true_for_new_roles(self):
        registry = RoleRegistry()
        assert registry.has("policy") is True
        assert registry.has("budget_execution") is True

    def test_unknown_role_id_raises_unsupported_role_error(self):
        registry = RoleRegistry()
        with pytest.raises(UnsupportedRoleError):
            registry.get("no_such_role")
