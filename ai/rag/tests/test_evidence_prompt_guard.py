"""
Unit Tests for ai.rag.evidence_sufficiency.prompt_guard
"""

from unittest.mock import patch

from ai.rag.evidence_sufficiency.prompt_guard import build_prompt_guard
from ai.rag.evidence_sufficiency.schemas import EvidenceSufficiencyStatus


class TestPromptGuard:
    def test_sufficient_guard_returned(self):
        guard = build_prompt_guard(EvidenceSufficiencyStatus.SUFFICIENT)
        assert "근거" in guard
        assert "임의로 추가하지" in guard

    def test_partial_guard_mentions_limited_evaluation(self):
        guard = build_prompt_guard(EvidenceSufficiencyStatus.PARTIAL)
        assert "제한적으로 평가" in guard
        assert "확정적인 점수는 생성하지 마세요" in guard

    def test_insufficient_guard_returned(self):
        guard = build_prompt_guard(EvidenceSufficiencyStatus.INSUFFICIENT)
        assert "부족" in guard

    def test_insufficient_guard_forbids_definitive_score(self):
        guard = build_prompt_guard(EvidenceSufficiencyStatus.INSUFFICIENT)
        assert "확정적인 평가 점수" in guard

    def test_insufficient_guard_forbids_fact_guessing(self):
        guard = build_prompt_guard(EvidenceSufficiencyStatus.INSUFFICIENT)
        assert "추측하지 마세요" in guard

    def test_insufficient_guard_requires_missing_info_disclosure(self):
        guard = build_prompt_guard(EvidenceSufficiencyStatus.INSUFFICIENT)
        assert "추가로 필요한 자료" in guard

    def test_insufficient_guard_forbids_pass_fail_conclusion(self):
        guard = build_prompt_guard(EvidenceSufficiencyStatus.INSUFFICIENT)
        assert "합격" in guard and "불합격" in guard

    def test_partial_guard_requires_uncertainty_disclosure(self):
        guard = build_prompt_guard(EvidenceSufficiencyStatus.PARTIAL)
        assert "단정하지" in guard

    def test_no_llm_call_involved(self):
        # LLM 호출 관련 모듈을 import하거나 사용하지 않는지, 순수 문자열 반환인지 확인한다.
        with patch("openai.OpenAI", create=True) as mock_client:
            build_prompt_guard(EvidenceSufficiencyStatus.SUFFICIENT)
            build_prompt_guard(EvidenceSufficiencyStatus.PARTIAL)
            build_prompt_guard(EvidenceSufficiencyStatus.INSUFFICIENT)
            mock_client.assert_not_called()

    def test_all_statuses_have_distinct_guards(self):
        guards = {
            build_prompt_guard(EvidenceSufficiencyStatus.SUFFICIENT),
            build_prompt_guard(EvidenceSufficiencyStatus.PARTIAL),
            build_prompt_guard(EvidenceSufficiencyStatus.INSUFFICIENT),
        }
        assert len(guards) == 3

    def test_returns_plain_string(self):
        guard = build_prompt_guard(EvidenceSufficiencyStatus.SUFFICIENT)
        assert isinstance(guard, str)
        assert len(guard) > 0
