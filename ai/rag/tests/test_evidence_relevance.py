"""
Unit Tests for ai.rag.evidence_linking.relevance
"""

from ai.rag.evidence_linking.config import EvidenceLinkingConfig
from ai.rag.evidence_linking.relevance import (
    calculate_relevance_score,
    extract_keywords,
    is_relevant_candidate,
)


class TestExtractKeywords:
    def test_stopwords_removed(self):
        keywords = extract_keywords("이 사업은 평가가 필요합니다.")
        assert "사업은" not in keywords
        assert "평가가" not in keywords
        assert "필요합니다" not in keywords

    def test_single_char_tokens_excluded(self):
        assert "이" not in extract_keywords("이 문서는 좋다")

    def test_meaningful_keywords_kept(self):
        keywords = extract_keywords("사업 추진 일정과 실행 계획이 부족합니다.")
        assert "추진" in keywords
        assert "실행" in keywords

    def test_empty_text_returns_empty_set(self):
        assert extract_keywords("") == set()
        assert extract_keywords(None) == set()


class TestIsRelevantCandidate:
    _OPINION = "사업 추진 일정과 실행 계획이 부족합니다."

    def test_content_overlap_accepted(self):
        assert is_relevant_candidate(
            self._OPINION,
            "1단계 기획, 2단계 개발, 3단계 실증 일정으로 진행한다.",
        ) is True

    def test_unrelated_content_rejected(self):
        assert is_relevant_candidate(
            self._OPINION,
            "목표 고객과 SNS 홍보 채널을 분석한다.",
            section_title="시장 분석 및 홍보 전략",
        ) is False

    def test_section_title_alone_can_establish_relevance(self):
        assert is_relevant_candidate(
            self._OPINION,
            "각 단계는 순차적으로 진행되며 세부 담당자는 별첨에 정리한다.",
            section_title="사업 추진 일정",
        ) is True

    def test_role_keyword_in_content_establishes_relevance(self):
        assert is_relevant_candidate(
            "이 사업의 전반적인 완성도를 평가해주세요.",
            "예산 및 자금조달, 재무 위험에 대한 설명이다.",
            role_keywords=["예산", "자금조달"],
        ) is True

    def test_generic_opinion_without_keywords_not_filtered(self):
        # 의견이 불용어로만 구성되어 의미 있는 키워드를 하나도 뽑지 못하면 필터링하지 않는다.
        assert is_relevant_candidate("부족합니다.", "아무 내용이나 상관없다.") is True

    def test_single_generic_stopword_overlap_is_not_enough(self):
        # "사업"만 겹치는 경우는 관련 근거로 인정하지 않는다.
        assert is_relevant_candidate(
            "사업 추진 일정과 실행 계획이 부족합니다.",
            "이 사업은 매우 훌륭한 사업입니다.",
        ) is False

    def test_custom_min_keyword_overlap_respected(self):
        # overlap 키워드가 1개뿐이면 min_keyword_overlap=2에서는 부족하고,
        # min_relevance_score도 높게 잡아 점수 기반 폴백으로도 통과하지 못하게 한다.
        config = EvidenceLinkingConfig(min_keyword_overlap=2, min_relevance_score=0.9)
        content = "계획만 있고 나머지는 무관한 내용이다."
        assert is_relevant_candidate(self._OPINION, content, config=config) is False


class TestCalculateRelevanceScore:
    def test_higher_overlap_yields_higher_score(self):
        opinion = "사업 추진 일정과 실행 계획이 부족합니다."
        high = calculate_relevance_score(
            opinion, "추진 일정과 실행 계획을 상세히 기술한다."
        )
        low = calculate_relevance_score(
            opinion, "목표 고객과 SNS 홍보 채널을 분석한다."
        )
        assert high > low

    def test_no_opinion_keywords_returns_zero(self):
        assert calculate_relevance_score("부족합니다.", "아무 내용") == 0.0
