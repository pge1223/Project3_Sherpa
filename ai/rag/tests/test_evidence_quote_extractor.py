"""
Unit Tests for ai.rag.evidence_linking.quote_extractor
"""

from ai.rag.evidence_linking.config import EvidenceLinkingConfig
from ai.rag.evidence_linking.quote_extractor import extract_quote, select_best_sentence, split_sentences


class TestSplitSentences:
    def test_splits_on_period_question_exclamation(self):
        content = "이것은 첫 문장이다. 이것은 질문인가? 이것은 감탄이다!"
        sentences = split_sentences(content)
        assert len(sentences) == 3

    def test_handles_korean_sentence_endings(self):
        content = "총사업비는 5,000만 원으로 산정하였다. 세부 사용 계획은 다음과 같습니다."
        sentences = split_sentences(content)
        assert len(sentences) == 2
        assert sentences[0] == "총사업비는 5,000만 원으로 산정하였다."

    def test_empty_content_returns_empty_list(self):
        assert split_sentences("") == []
        assert split_sentences("   ") == []

    def test_each_sentence_is_substring_of_content(self):
        content = "예산은 5천만원이다. 인건비는 2천만원이다."
        for sentence in split_sentences(content):
            assert sentence in content


class TestSelectBestSentence:
    def test_prefers_sentence_with_more_common_keywords(self):
        opinion = "예산 산정 기준과 세부 사용 계획이 부족합니다."
        sentences = [
            "이 사업의 목표 고객은 20대이다.",
            "총사업비는 5,000만 원으로 산정하였으며 세부 사용 계획을 포함한다.",
        ]
        best = select_best_sentence(opinion, sentences)
        assert best == sentences[1]

    def test_no_relevant_sentence_returns_none(self):
        opinion = "예산 산정 기준이 부족합니다."
        sentences = ["전혀 관련 없는 내용입니다.", "완전히 다른 주제의 문장입니다."]
        assert select_best_sentence(opinion, sentences) is None

    def test_empty_sentence_list_returns_none(self):
        assert select_best_sentence("의견", []) is None

    def test_role_keywords_contribute_to_score(self):
        opinion = "이 사업의 전반적인 완성도를 평가해주세요."
        sentences = [
            "고객 응대 매뉴얼이 준비되어 있다.",
            "예산 및 자금조달 계획이 상세히 기술되어 있다.",
        ]
        best = select_best_sentence(opinion, sentences, role_keywords=["예산", "자금조달"])
        assert best == sentences[1]


class TestExtractQuote:
    def test_extracts_relevant_sentence(self):
        config = EvidenceLinkingConfig()
        content = "이 문서는 사업 개요를 다룬다. 총사업비는 5,000만 원으로 산정하였다."
        opinion = "예산 산정 기준이 명확하지 않습니다. 총사업비 근거가 부족합니다."
        quote = extract_quote(content, opinion, config)
        assert "총사업비" in quote
        assert quote in content

    def test_fallback_to_content_prefix_when_no_relevant_sentence(self):
        config = EvidenceLinkingConfig(quote_context_length=10)
        content = "전혀 관련 없는 내용의 문서입니다. 다른 주제를 다룹니다."
        opinion = "예산 산정 기준이 부족합니다."
        quote = extract_quote(content, opinion, config)
        assert quote == content[:10]

    def test_quote_max_length_truncates_with_ellipsis(self):
        config = EvidenceLinkingConfig(quote_max_length=20)
        long_sentence = "예산 산정 기준은 다음과 같이 상세하게 기술되어 있으며 세부 항목별로 나뉘어 있다."
        content = long_sentence
        opinion = "예산 산정 기준이 부족합니다."
        quote = extract_quote(content, opinion, config)
        assert len(quote) <= config.quote_max_length
        assert quote.endswith("…")

    def test_empty_content_returns_empty_string(self):
        config = EvidenceLinkingConfig()
        assert extract_quote("", "의견", config) == ""
        assert extract_quote("   ", "의견", config) == ""

    def test_quote_never_contains_text_absent_from_content(self):
        config = EvidenceLinkingConfig()
        content = "총사업비는 5,000만 원으로 산정하였다. 세부 사용 계획은 별첨과 같다."
        opinion = "예산 세부 사용 계획이 궁금합니다."
        quote = extract_quote(content, opinion, config)
        stripped = quote.rstrip("…")
        assert stripped in content
