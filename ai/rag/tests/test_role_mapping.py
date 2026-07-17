"""
Unit Tests for ai.rag.orchestration.role_mapping
(순수 함수 — 실제 Chroma/KURE/LLM/LangGraph 없음)
"""

import logging

import pytest

from ai.rag.orchestration.role_mapping import (
    PersonaRoleMappingError,
    RoleMappingConfig,
    resolve_role_id,
    supported_domains,
)


class TestCompetitionMapping:
    @pytest.mark.parametrize(
        "persona_id, expected_role_id",
        [
            ("creativity_originality", "marketing"),
            ("technical_feasibility", "technology"),
            ("business_strategy", "finance"),
            ("presentation_completeness", "planning"),
        ],
    )
    def test_competition_persona_maps_to_expected_role(self, persona_id, expected_role_id):
        assert resolve_role_id(domain="competition", persona_id=persona_id) == expected_role_id

    def test_criterion_id_does_not_change_default_mapping_when_no_override(self):
        # override가 없으면 criterion_id를 무엇을 넘겨도 persona 기본 매핑으로 떨어진다.
        assert (
            resolve_role_id(domain="competition", persona_id="business_strategy", criterion_id="contribution")
            == "finance"
        )
        assert (
            resolve_role_id(domain="competition", persona_id="business_strategy", criterion_id="other_criterion")
            == "finance"
        )


class TestUnknownDomainAndPersona:
    def test_unknown_domain_raises_without_fallback(self):
        with pytest.raises(PersonaRoleMappingError):
            resolve_role_id(domain="unknown_domain", persona_id="business_strategy")

    def test_unknown_persona_in_known_domain_raises_without_fallback(self):
        with pytest.raises(PersonaRoleMappingError):
            resolve_role_id(domain="competition", persona_id="unknown_persona")

    def test_government_support_not_yet_configured(self):
        # 팀이 아직 확정하지 않은 도메인 -- 임의로 매핑을 추가하지 않았으므로 미지원이어야 한다.
        assert "government_support" not in supported_domains()
        with pytest.raises(PersonaRoleMappingError):
            resolve_role_id(domain="government_support", persona_id="business_strategy")


class TestStrictDefaultAndFallback:
    def test_default_config_does_not_allow_semantic_fallback(self):
        config = RoleMappingConfig()
        assert config.allow_semantic_fallback is False
        with pytest.raises(PersonaRoleMappingError):
            resolve_role_id(domain="unknown_domain", persona_id="unknown_persona", config=config)

    def test_fallback_enabled_returns_none_role_id(self):
        config = RoleMappingConfig(allow_semantic_fallback=True)
        role_id = resolve_role_id(domain="unknown_domain", persona_id="unknown_persona", config=config)
        assert role_id is None

    def test_fallback_enabled_logs_warning(self, caplog):
        config = RoleMappingConfig(allow_semantic_fallback=True)
        with caplog.at_level(logging.WARNING, logger="ai.rag.orchestration.role_mapping"):
            resolve_role_id(domain="unknown_domain", persona_id="unknown_persona", config=config)
        assert any("PERSONA_ROLE_MAPPING_FALLBACK" in record.message for record in caplog.records)

    def test_known_mapping_takes_priority_over_fallback(self):
        # 매핑이 있으면 allow_semantic_fallback=True여도 fallback을 타지 않고 실제 매핑을 쓴다.
        config = RoleMappingConfig(allow_semantic_fallback=True)
        role_id = resolve_role_id(domain="competition", persona_id="business_strategy", config=config)
        assert role_id == "finance"


class TestSupportedDomains:
    def test_competition_listed(self):
        assert "competition" in supported_domains()
