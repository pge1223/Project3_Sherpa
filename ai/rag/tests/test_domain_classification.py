"""
Unit Tests for ai.rag.domain_classification (DOM-001)
==========================================================
LLM은 항상 stub(Callable[[str], str])으로 주입한다 — 실제 API 호출 없음.
"""

from __future__ import annotations

import json

import pytest

from ai.rag.chunking.schemas import Chunk, ChunkLocationType, ContentKind, SourceType
from ai.rag.domain_classification.config import DomainClassificationConfig
from ai.rag.domain_classification.normalize import normalize_confidence, normalize_domain_label
from ai.rag.domain_classification.prompt import build_classification_prompt
from ai.rag.domain_classification.schemas import DomainClassificationRequest, DomainLabel
from ai.rag.domain_classification.service import (
    DomainClassificationError,
    DomainClassificationService,
)


def _make_chunk(*, chunk_id: str, content: str, chunk_index: int = 0) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        document_id="doc-1",
        content=content,
        chunk_index=chunk_index,
        content_kind=ContentKind.BODY,
        source_type=SourceType.FILE_UPLOAD,
        location_type=ChunkLocationType.PAGE,
        location_number=1,
        char_count=len(content),
    )


class _CountingStub:
    def __init__(self, response: str):
        self.response = response
        self.call_count = 0
        self.last_prompt: str | None = None

    def __call__(self, prompt: str) -> str:
        self.call_count += 1
        self.last_prompt = prompt
        return self.response


def _response(domain: str, confidence: float, reasoning: str = "근거", scores: dict | None = None) -> str:
    payload = {"domain": domain, "confidence": confidence, "reasoning": reasoning}
    if scores is not None:
        payload["scores"] = scores
    return json.dumps(payload)


class TestNormalizeConfidence:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (0.8, 0.8),
            (1, 1.0),
            ("0.8", 0.8),
            ("80%", 0.8),
            (80, 0.8),  # 1보다 크면 백분율로 간주
            (150, 1.0),  # 상한 clamp
            (-5, 0.0),  # 하한 clamp (문자열 파싱 경로가 아니라 숫자 경로는 음수도 통과 후 clamp)
            (None, None),
            ("", None),
            ("모름", None),
            (True, None),
        ],
    )
    def test_normalize_confidence(self, raw, expected):
        assert normalize_confidence(raw) == expected


class TestNormalizeDomainLabel:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("competition", DomainLabel.COMPETITION),
            ("Government_Support", DomainLabel.GOVERNMENT_SUPPORT),
            ("  startup  ", DomainLabel.STARTUP),
            ("unknown", None),  # unknown은 LLM이 직접 고르는 라벨이 아님
            ("공모전", None),
            (None, None),
            (123, None),
        ],
    )
    def test_normalize_domain_label(self, raw, expected):
        assert normalize_domain_label(raw) == expected


class TestBuildClassificationPrompt:
    def test_raises_on_empty_text(self):
        with pytest.raises(ValueError):
            build_classification_prompt("   ")

    def test_includes_document_text(self):
        prompt = build_classification_prompt("2026 디자인 공모전 모집요강")
        assert "2026 디자인 공모전 모집요강" in prompt


class TestDomainClassificationServiceEmptyDocument:
    def test_empty_chunks_and_text_returns_unknown_without_calling_llm(self):
        stub = _CountingStub(response="{}")
        service = DomainClassificationService(llm_call=stub)
        result = service.classify(DomainClassificationRequest(chunks=[], text=None))

        assert stub.call_count == 0
        assert result.domain == DomainLabel.UNKNOWN
        assert result.confidence == 0.0
        assert result.warnings

    def test_whitespace_only_chunks_returns_unknown_without_calling_llm(self):
        stub = _CountingStub(response="{}")
        service = DomainClassificationService(llm_call=stub)
        chunk = _make_chunk(chunk_id="c1", content="   \n\t  ")
        result = service.classify(DomainClassificationRequest(chunks=[chunk]))

        assert stub.call_count == 0
        assert result.domain == DomainLabel.UNKNOWN


class TestDomainClassificationServiceNormalCases:
    def test_competition_document_classified_with_high_confidence(self):
        stub = _CountingStub(
            response=_response(
                "competition",
                0.92,
                "창의성과 독창성을 평가하는 디자인 공모전 모집요강임",
                scores={"competition": 0.92, "government_support": 0.03, "startup": 0.05},
            )
        )
        service = DomainClassificationService(llm_call=stub)
        chunk = _make_chunk(
            chunk_id="c1",
            content="2026 제4회 에너지최적화 디자인 공모전 모집요강. 창의성 및 적정성, 실현 가능성을 심사한다.",
        )
        result = service.classify(DomainClassificationRequest(chunks=[chunk]))

        assert stub.call_count == 1
        assert result.domain == DomainLabel.COMPETITION
        assert result.confidence == pytest.approx(0.92)
        assert result.candidate_scores["competition"] == pytest.approx(0.92)
        assert result.raw_domain_label == "competition"

    def test_government_support_document_classified_with_high_confidence(self):
        stub = _CountingStub(
            response=_response(
                "government_support",
                0.88,
                "정책목표 부합성과 예산 집행계획을 평가하는 정부 지원사업 공고임",
            )
        )
        service = DomainClassificationService(llm_call=stub)
        chunk = _make_chunk(
            chunk_id="c1",
            content="2026년 지역 소상공인 디지털 전환 지원사업 공고. 신청 자격 및 예산 편성 기준을 안내한다.",
        )
        result = service.classify(DomainClassificationRequest(chunks=[chunk]))

        assert result.domain == DomainLabel.GOVERNMENT_SUPPORT
        assert result.confidence == pytest.approx(0.88)

    def test_startup_document_classified_even_without_rubric_mapping(self):
        # rubric_mapping_startup.json이 없어도 분류 자체는 정상 동작해야 한다
        # (분류 가능 여부와 회의 실행 가능 여부는 분리된 관심사).
        stub = _CountingStub(
            response=_response(
                "startup",
                0.81,
                "문제-고객-시장-수익모델과 투자 유치 준비도를 다루는 IR 심사 자료임",
            )
        )
        service = DomainClassificationService(llm_call=stub)
        chunk = _make_chunk(
            chunk_id="c1",
            content="본 사업계획서는 타겟 고객과 시장 규모, 수익모델, 투자 유치 계획을 설명한다.",
        )
        result = service.classify(DomainClassificationRequest(chunks=[chunk]))

        assert result.domain == DomainLabel.STARTUP
        assert result.confidence == pytest.approx(0.81)


class TestDomainClassificationServiceAmbiguousAndLowConfidence:
    def test_ambiguous_document_with_low_confidence_falls_back_to_unknown(self):
        stub = _CountingStub(
            response=_response(
                "government_support",
                0.35,
                "지원사업 공고와 공모전 모집요강의 특징이 섞여 있어 확신하기 어려움",
                scores={"competition": 0.3, "government_support": 0.35, "startup": 0.2},
            )
        )
        service = DomainClassificationService(llm_call=stub)
        chunk = _make_chunk(chunk_id="c1", content="본 사업은 참가 신청을 받아 심사 후 지원금을 지급한다.")
        result = service.classify(DomainClassificationRequest(chunks=[chunk]))

        assert result.domain == DomainLabel.UNKNOWN
        assert result.confidence == pytest.approx(0.35)
        assert result.raw_domain_label == "government_support"  # 원본 라벨은 진단용으로 남는다
        assert any("임계값" in warning for warning in result.warnings)

    def test_low_confidence_threshold_is_configurable(self):
        stub = _CountingStub(response=_response("startup", 0.5, "약한 단서"))
        strict_service = DomainClassificationService(
            llm_call=stub, config=DomainClassificationConfig(min_confidence=0.6)
        )
        lenient_service = DomainClassificationService(
            llm_call=stub, config=DomainClassificationConfig(min_confidence=0.4)
        )
        chunk = _make_chunk(chunk_id="c1", content="사업계획 개요")

        strict_result = strict_service.classify(DomainClassificationRequest(chunks=[chunk]))
        lenient_result = lenient_service.classify(DomainClassificationRequest(chunks=[chunk]))

        assert strict_result.domain == DomainLabel.UNKNOWN
        assert lenient_result.domain == DomainLabel.STARTUP

    def test_unknown_label_from_llm_falls_back_to_unknown(self):
        stub = _CountingStub(response=_response("정부지원사업", 0.9, "라벨을 한국어로 응답함"))
        service = DomainClassificationService(llm_call=stub)
        chunk = _make_chunk(chunk_id="c1", content="문서 내용")
        result = service.classify(DomainClassificationRequest(chunks=[chunk]))

        assert result.domain == DomainLabel.UNKNOWN
        assert result.raw_domain_label == "정부지원사업"
        assert any("알려진 라벨" in warning for warning in result.warnings)

    def test_unparsable_confidence_falls_back_to_unknown(self):
        stub = _CountingStub(
            response=json.dumps({"domain": "competition", "confidence": "모름", "reasoning": "근거"})
        )
        service = DomainClassificationService(llm_call=stub)
        chunk = _make_chunk(chunk_id="c1", content="문서 내용")
        result = service.classify(DomainClassificationRequest(chunks=[chunk]))

        assert result.domain == DomainLabel.UNKNOWN
        assert result.confidence == 0.0
        assert any("해석할 수 없습니다" in warning for warning in result.warnings)


class TestDomainClassificationServiceMalformedResponses:
    def test_non_json_response_raises(self):
        service = DomainClassificationService(llm_call=lambda prompt: "이건 JSON이 아닙니다")
        chunk = _make_chunk(chunk_id="c1", content="문서 내용")

        with pytest.raises(DomainClassificationError):
            service.classify(DomainClassificationRequest(chunks=[chunk]))

    def test_json_array_response_raises(self):
        service = DomainClassificationService(llm_call=lambda prompt: json.dumps(["competition"]))
        chunk = _make_chunk(chunk_id="c1", content="문서 내용")

        with pytest.raises(DomainClassificationError):
            service.classify(DomainClassificationRequest(chunks=[chunk]))

    def test_markdown_fenced_json_response_is_parsed(self):
        fenced = "```json\n" + _response("competition", 0.9, "근거") + "\n```"
        service = DomainClassificationService(llm_call=lambda prompt: fenced)
        chunk = _make_chunk(chunk_id="c1", content="문서 내용")

        result = service.classify(DomainClassificationRequest(chunks=[chunk]))

        assert result.domain == DomainLabel.COMPETITION

    def test_invalid_scores_field_ignored_with_warning(self):
        response = json.dumps(
            {"domain": "competition", "confidence": 0.9, "reasoning": "근거", "scores": "oops"}
        )
        service = DomainClassificationService(llm_call=lambda prompt: response)
        chunk = _make_chunk(chunk_id="c1", content="문서 내용")

        result = service.classify(DomainClassificationRequest(chunks=[chunk]))

        assert result.domain == DomainLabel.COMPETITION
        assert result.candidate_scores == {}
        assert any("scores" in warning for warning in result.warnings)


class TestDomainClassificationServiceTextInput:
    def test_text_field_used_instead_of_chunks(self):
        stub = _CountingStub(response=_response("startup", 0.85, "근거"))
        service = DomainClassificationService(llm_call=stub)

        result = service.classify(
            DomainClassificationRequest(chunks=[], text="타겟 고객과 시장 규모, 수익모델을 설명한다.")
        )

        assert result.domain == DomainLabel.STARTUP
        assert "타겟 고객과 시장 규모" in stub.last_prompt

    def test_chunks_truncated_to_max_input_chars(self):
        stub = _CountingStub(response=_response("competition", 0.9, "근거"))
        config = DomainClassificationConfig(max_input_chars=10)
        service = DomainClassificationService(llm_call=stub, config=config)
        chunk = _make_chunk(chunk_id="c1", content="가나다라마바사아자차카타파하")

        service.classify(DomainClassificationRequest(chunks=[chunk]))

        document_section = stub.last_prompt.split("문서 발췌:\n", 1)[1]
        assert len(document_section) == 10

    def test_chunks_joined_in_chunk_index_order(self):
        stub = _CountingStub(response=_response("competition", 0.9, "근거"))
        service = DomainClassificationService(llm_call=stub)
        second = _make_chunk(chunk_id="c2", content="두번째", chunk_index=1)
        first = _make_chunk(chunk_id="c1", content="첫번째", chunk_index=0)

        service.classify(DomainClassificationRequest(chunks=[second, first]))

        document_section = stub.last_prompt.split("문서 발췌:\n", 1)[1]
        assert document_section.index("첫번째") < document_section.index("두번째")
