"""
Unit/Integration Tests for ai.rag.criteria_extraction
=========================================================
LLM은 항상 stub(Callable[[str], str])으로 주입한다 — 실제 API 호출 없음.
"""

from __future__ import annotations

import json
import re

import pytest

from ai.rag.chunking.chunker import chunk_document
from ai.rag.chunking.schemas import (
    Chunk,
    ChunkLocationType,
    ChunkSourceContext,
    ContentKind,
    SourceType,
)
from ai.rag.criteria_extraction.normalize import normalize_criterion_key, normalize_weight
from ai.rag.criteria_extraction.prompt import build_extraction_prompt
from ai.rag.criteria_extraction.schemas import (
    CriteriaExtractionRequest,
    ExtractionStatus,
)
from ai.rag.criteria_extraction.selection import select_candidate_chunks
from ai.rag.criteria_extraction.service import CriteriaExtractionError, CriteriaExtractionService
from ai.rag.parsers.schemas import (
    BlockType,
    DocumentBlock,
    DocumentExtractionResult,
    FileType,
    LocationType,
)


def _make_chunk(
    *,
    chunk_id: str,
    content: str,
    content_kind: ContentKind = ContentKind.BODY,
    section_title: str | None = None,
    location_number: int | None = None,
    indexable: bool = True,
    document_id: str = "doc-1",
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        document_id=document_id,
        content=content,
        chunk_index=0,
        content_kind=content_kind,
        source_type=SourceType.FILE_UPLOAD,
        location_type=ChunkLocationType.PAGE,
        location_number=location_number,
        section_title=section_title,
        char_count=len(content),
        indexable=indexable,
    )


class TestNormalizeWeight:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (20, 20.0),
            (20.5, 20.5),
            ("20", 20.0),
            ("20점", 20.0),
            (" 20 점 ", 20.0),
            ("총 20점 만점", 20.0),
            ("20%", 20.0),
            (None, None),
            ("", None),
            ("   ", None),
            ("배점은 별도 공고 예정", None),
            ("배점 미공개", None),
            (True, None),  # bool은 int의 서브클래스라 명시적으로 제외
        ],
    )
    def test_normalize_weight(self, raw, expected):
        assert normalize_weight(raw) == expected

    def test_normalize_weight_rejects_non_string_non_number(self):
        assert normalize_weight(["20"]) is None


class TestNormalizeCriterionKey:
    def test_ignores_whitespace_and_case(self):
        assert normalize_criterion_key("사업 필요성") == normalize_criterion_key("사업필요성")

    def test_different_names_produce_different_keys(self):
        assert normalize_criterion_key("사업 필요성") != normalize_criterion_key("사업화 가능성")


class TestSelectCandidateChunks:
    def test_table_chunk_always_selected(self):
        table_chunk = _make_chunk(chunk_id="c1", content="아무 텍스트", content_kind=ContentKind.TABLE)
        assert select_candidate_chunks([table_chunk]) == [table_chunk]

    def test_body_chunk_selected_only_with_keyword(self):
        with_keyword = _make_chunk(chunk_id="c1", content="본 사업의 평가기준은 다음과 같다.")
        without_keyword = _make_chunk(chunk_id="c2", content="접수 문의는 이메일로 받는다.")
        result = select_candidate_chunks([with_keyword, without_keyword])
        assert result == [with_keyword]

    def test_keyword_in_section_title_is_enough(self):
        chunk = _make_chunk(chunk_id="c1", content="일정, 예산 배분 계획", section_title="심사기준")
        assert select_candidate_chunks([chunk]) == [chunk]

    def test_non_indexable_chunk_excluded_even_with_keyword(self):
        toc_chunk = _make_chunk(
            chunk_id="c1", content="평가기준 ..................... 8", indexable=False
        )
        assert select_candidate_chunks([toc_chunk]) == []

    def test_result_sorted_by_chunk_index(self):
        first = _make_chunk(chunk_id="c1", content="평가기준 항목 A").model_copy(update={"chunk_index": 5})
        second = _make_chunk(chunk_id="c2", content="평가기준 항목 B").model_copy(update={"chunk_index": 1})
        assert select_candidate_chunks([first, second]) == [second, first]


class TestBuildExtractionPrompt:
    def test_raises_on_empty_candidates(self):
        with pytest.raises(ValueError):
            build_extraction_prompt([])

    def test_includes_chunk_id_and_page_markers(self):
        chunk = _make_chunk(chunk_id="c1", content="평가기준: 사업 필요성", location_number=8)
        prompt = build_extraction_prompt([chunk])
        assert "[chunk_id=c1 page=8]" in prompt
        assert "평가기준: 사업 필요성" in prompt

    def test_unknown_page_label_when_location_number_missing(self):
        chunk = _make_chunk(chunk_id="c1", content="평가기준: 사업 필요성", location_number=None)
        prompt = build_extraction_prompt([chunk])
        assert "page=unknown" in prompt


class _CountingStub:
    """호출 횟수를 세는 stub LLM — "후보가 없으면 LLM을 호출하지 않는다"를 검증하는 용도."""

    def __init__(self, response: str):
        self.response = response
        self.call_count = 0

    def __call__(self, prompt: str) -> str:
        self.call_count += 1
        return self.response


class TestCriteriaExtractionServiceGating:
    def test_wrong_document_role_skips_without_calling_llm(self):
        stub = _CountingStub(response="{}")
        service = CriteriaExtractionService(llm_call=stub)
        chunk = _make_chunk(chunk_id="c1", content="평가기준: 사업 필요성")
        request = CriteriaExtractionRequest(
            domain="government_support",
            notice_document_id="NOTICE-1",
            chunks=[chunk],
            document_role="target",
        )

        result = service.extract(request)

        assert stub.call_count == 0
        assert result.criteria == []
        assert result.meta.extraction_status == ExtractionStatus.SKIPPED_WRONG_ROLE

    def test_no_candidate_section_skips_without_calling_llm(self):
        stub = _CountingStub(response="{}")
        service = CriteriaExtractionService(llm_call=stub)
        chunk = _make_chunk(chunk_id="c1", content="접수 문의는 이메일로 받는다.")
        request = CriteriaExtractionRequest(
            domain="government_support",
            notice_document_id="NOTICE-1",
            chunks=[chunk],
        )

        result = service.extract(request)

        assert stub.call_count == 0
        assert result.criteria == []
        assert result.meta.extraction_status == ExtractionStatus.NO_CANDIDATE_SECTION

    def test_malformed_json_response_raises(self):
        service = CriteriaExtractionService(llm_call=lambda prompt: "이건 JSON이 아닙니다")
        chunk = _make_chunk(chunk_id="c1", content="평가기준: 사업 필요성")
        request = CriteriaExtractionRequest(
            domain="government_support", notice_document_id="NOTICE-1", chunks=[chunk]
        )

        with pytest.raises(CriteriaExtractionError):
            service.extract(request)

    def test_criteria_not_list_raises(self):
        service = CriteriaExtractionService(llm_call=lambda prompt: json.dumps({"criteria": "oops"}))
        chunk = _make_chunk(chunk_id="c1", content="평가기준: 사업 필요성")
        request = CriteriaExtractionRequest(
            domain="government_support", notice_document_id="NOTICE-1", chunks=[chunk]
        )

        with pytest.raises(CriteriaExtractionError):
            service.extract(request)

    def test_empty_criteria_array_reports_not_found(self):
        service = CriteriaExtractionService(llm_call=lambda prompt: json.dumps({"criteria": []}))
        chunk = _make_chunk(chunk_id="c1", content="평가기준: 사업 필요성")
        request = CriteriaExtractionRequest(
            domain="government_support", notice_document_id="NOTICE-1", chunks=[chunk]
        )

        result = service.extract(request)

        assert result.criteria == []
        assert result.meta.extraction_status == ExtractionStatus.NOT_FOUND


class TestCriteriaExtractionServiceNormalizationAndDedup:
    def _service_with_response(self, raw_items: list[dict]) -> CriteriaExtractionService:
        return CriteriaExtractionService(llm_call=lambda prompt: json.dumps({"criteria": raw_items}))

    def test_weight_string_normalized_and_page_resolved_from_source_chunk_id(self):
        chunk = _make_chunk(
            chunk_id="chk_a",
            content="사업 필요성: 정책 부합 여부를 평가한다. (20점)",
            content_kind=ContentKind.TABLE,
            location_number=8,
        )
        service = self._service_with_response(
            [
                {
                    "criterion_id": "necessity",
                    "name": "사업 필요성",
                    "description": "정책 부합 여부",
                    "weight": "20점",
                    "source_text": "정책 부합 여부를 평가한다.",
                    "source_chunk_id": "chk_a",
                }
            ]
        )
        request = CriteriaExtractionRequest(
            domain="government_support", notice_document_id="NOTICE-1", chunks=[chunk]
        )

        result = service.extract(request)

        assert result.meta.extraction_status == ExtractionStatus.EXTRACTED
        assert len(result.criteria) == 1
        criterion = result.criteria[0]
        assert criterion.weight == 20.0
        assert criterion.page == 8
        assert criterion.source_chunk_id == "chk_a"

    def test_weight_null_when_not_disclosed_in_notice(self):
        chunk = _make_chunk(chunk_id="chk_a", content="추진계획 적정성을 평가한다.", content_kind=ContentKind.TABLE)
        service = self._service_with_response(
            [
                {
                    "criterion_id": "execution_plan",
                    "name": "추진계획 적정성",
                    "description": "일정과 예산 계획의 구체성",
                    "weight": None,
                    "source_text": "추진계획 적정성을 평가한다.",
                    "source_chunk_id": "chk_a",
                }
            ]
        )
        request = CriteriaExtractionRequest(
            domain="government_support", notice_document_id="NOTICE-1", chunks=[chunk]
        )

        result = service.extract(request)

        assert result.criteria[0].weight is None

    def test_duplicate_criterion_id_deduplicated(self):
        chunk = _make_chunk(chunk_id="chk_a", content="사업 필요성 평가기준")
        service = self._service_with_response(
            [
                {
                    "criterion_id": "necessity",
                    "name": "사업 필요성",
                    "description": "설명 A",
                    "weight": 20,
                    "source_text": "원문 A",
                    "source_chunk_id": "chk_a",
                },
                {
                    "criterion_id": "necessity",
                    "name": "사업 필요성(중복)",
                    "description": "설명 B",
                    "weight": 30,
                    "source_text": "원문 B",
                    "source_chunk_id": "chk_a",
                },
            ]
        )
        request = CriteriaExtractionRequest(
            domain="government_support", notice_document_id="NOTICE-1", chunks=[chunk]
        )

        result = service.extract(request)

        assert len(result.criteria) == 1
        assert result.criteria[0].description == "설명 A"
        assert any("necessity" in warning for warning in result.meta.warnings)

    def test_duplicate_name_with_different_id_deduplicated(self):
        chunk = _make_chunk(chunk_id="chk_a", content="사업 필요성 평가기준")
        service = self._service_with_response(
            [
                {
                    "criterion_id": "necessity",
                    "name": "사업 필요성",
                    "description": "설명 A",
                    "weight": 20,
                    "source_text": "원문 A",
                    "source_chunk_id": "chk_a",
                },
                {
                    "criterion_id": "necessity_2",
                    "name": "사업  필요성",  # 공백만 다름
                    "description": "설명 B",
                    "weight": 20,
                    "source_text": "원문 B",
                    "source_chunk_id": "chk_a",
                },
            ]
        )
        request = CriteriaExtractionRequest(
            domain="government_support", notice_document_id="NOTICE-1", chunks=[chunk]
        )

        result = service.extract(request)

        assert len(result.criteria) == 1

    def test_missing_required_field_skipped_with_warning(self):
        chunk = _make_chunk(chunk_id="chk_a", content="평가기준 텍스트")
        service = self._service_with_response(
            [
                {
                    "criterion_id": "",
                    "name": "이름만 있음",
                    "description": "설명",
                    "weight": None,
                    "source_text": "원문",
                }
            ]
        )
        request = CriteriaExtractionRequest(
            domain="government_support", notice_document_id="NOTICE-1", chunks=[chunk]
        )

        result = service.extract(request)

        assert result.criteria == []
        assert result.meta.extraction_status == ExtractionStatus.NOT_FOUND
        assert result.meta.warnings

    def test_unknown_source_chunk_id_leaves_page_none_with_warning(self):
        chunk = _make_chunk(chunk_id="chk_a", content="평가기준 텍스트")
        service = self._service_with_response(
            [
                {
                    "criterion_id": "necessity",
                    "name": "사업 필요성",
                    "description": "설명",
                    "weight": 20,
                    "source_text": "원문",
                    "source_chunk_id": "chk_does_not_exist",
                }
            ]
        )
        request = CriteriaExtractionRequest(
            domain="government_support", notice_document_id="NOTICE-1", chunks=[chunk]
        )

        result = service.extract(request)

        assert result.criteria[0].page is None
        assert any("chk_does_not_exist" in warning for warning in result.meta.warnings)

    def test_markdown_fenced_json_response_is_parsed(self):
        chunk = _make_chunk(chunk_id="chk_a", content="평가기준 텍스트")
        fenced = "```json\n" + json.dumps(
            {
                "criteria": [
                    {
                        "criterion_id": "necessity",
                        "name": "사업 필요성",
                        "description": "설명",
                        "weight": 20,
                        "source_text": "원문",
                        "source_chunk_id": "chk_a",
                    }
                ]
            }
        ) + "\n```"
        service = CriteriaExtractionService(llm_call=lambda prompt: fenced)
        request = CriteriaExtractionRequest(
            domain="government_support", notice_document_id="NOTICE-1", chunks=[chunk]
        )

        result = service.extract(request)

        assert len(result.criteria) == 1


# ---------------------------------------------------------------------------
# 통합 테스트: 실제 공고문 형태의 문서를 chunk_document()로 청킹한 뒤
# CriteriaExtractionService에 그대로 넘겨 end-to-end로 검증한다.
# ---------------------------------------------------------------------------

_CHUNK_MARKER_RE = re.compile(
    r"\[chunk_id=(?P<chunk_id>\S+) page=(?P<page>\S+)\]\n(?P<content>.*?)(?=\n\[chunk_id=|\Z)",
    re.DOTALL,
)


def _stub_llm_from_prompt(prompt: str) -> str:
    """실제 LLM 대신, 프롬프트에 실린 발췌문 중 알려진 문구가 있는 발췌문의
    chunk_id를 근거로 삼아 criteria를 만들어 반환하는 stub. ai/meeting/tests/test_graph.py의
    "프롬프트 안 마커로 분기하는 stub" 관례를 따른다."""
    criteria = []
    for match in _CHUNK_MARKER_RE.finditer(prompt):
        chunk_id = match.group("chunk_id")
        content = match.group("content")
        if "사업 필요성" in content:
            criteria.append(
                {
                    "criterion_id": "necessity",
                    "name": "사업 필요성",
                    "description": "지원사업 목적 및 정책 방향에 부합하는지 평가",
                    "weight": "20점",
                    "source_text": "본 사업의 필요성 및 추진 배경이 명확한지 평가한다.",
                    "source_chunk_id": chunk_id,
                }
            )
        if "사업화 가능성" in content:
            criteria.append(
                {
                    "criterion_id": "feasibility",
                    "name": "사업화 가능성",
                    "description": "시장성과 사업화 실현 가능성",
                    "weight": None,
                    "source_text": "제품·서비스의 시장 진입 가능성을 평가한다.",
                    "source_chunk_id": chunk_id,
                }
            )
    return json.dumps({"criteria": criteria})


def _build_notice_extraction_result() -> DocumentExtractionResult:
    blocks = [
        DocumentBlock(
            block_id="b0",
            block_type=BlockType.TITLE,
            content="2026년 지역 소상공인 디지털 전환 지원사업 공고",
            location_type=LocationType.PAGE,
            location_number=1,
            order=0,
        ),
        DocumentBlock(
            block_id="b1",
            block_type=BlockType.TEXT,
            content="본 사업은 지역 소상공인의 디지털 전환을 지원하기 위해 추진한다. 신청 자격은 소상공인이다.",
            location_type=LocationType.PAGE,
            location_number=1,
            order=1,
        ),
        DocumentBlock(
            block_id="b2",
            block_type=BlockType.TITLE,
            content="평가기준",
            location_type=LocationType.PAGE,
            location_number=8,
            order=2,
        ),
        DocumentBlock(
            block_id="b3",
            block_type=BlockType.TEXT,
            content=(
                "가. 사업 필요성: 본 사업의 필요성 및 추진 배경이 명확한지 평가한다. (20점)\n"
                "나. 사업화 가능성: 제품·서비스의 시장 진입 가능성을 평가한다. (배점 별도 공고 예정)"
            ),
            location_type=LocationType.PAGE,
            location_number=8,
            order=3,
        ),
        DocumentBlock(
            block_id="b4",
            block_type=BlockType.TEXT,
            content="문의처: 사업 담당자 이메일로 문의 바랍니다.",
            location_type=LocationType.PAGE,
            location_number=9,
            order=4,
        ),
    ]
    return DocumentExtractionResult(
        document_id="doc-notice-1",
        file_name="notice.pdf",
        file_type=FileType.PDF,
        file_size=1024,
        page_count=9,
        block_count=len(blocks),
        blocks=blocks,
    )


class TestCriteriaExtractionIntegration:
    def test_extracts_criteria_from_chunked_notice_document(self):
        extraction_result = _build_notice_extraction_result()
        context = ChunkSourceContext(
            document_id="doc-notice-1",
            source_type=SourceType.FILE_UPLOAD,
            source_filename="notice.pdf",
        )
        chunking_result = chunk_document(extraction_result, context)

        service = CriteriaExtractionService(llm_call=_stub_llm_from_prompt)
        request = CriteriaExtractionRequest(
            domain="government_support",
            notice_document_id="NOTICE-MOCK-GOV-001",
            notice_title="2026년 지역 소상공인 디지털 전환 지원사업 공고(예시)",
            chunks=chunking_result.chunks,
        )

        result = service.extract(request)

        assert result.meta.extraction_status == ExtractionStatus.EXTRACTED
        assert result.domain == "government_support"
        assert result.notice_document_id == "NOTICE-MOCK-GOV-001"

        by_id = {criterion.criterion_id: criterion for criterion in result.criteria}
        assert set(by_id) == {"necessity", "feasibility"}

        necessity = by_id["necessity"]
        assert necessity.weight == 20.0
        assert necessity.page == 8  # source_chunk_id로 역추적된 페이지
        assert necessity.source_chunk_id is not None

        feasibility = by_id["feasibility"]
        assert feasibility.weight is None  # 공고문에 배점 미공개 -> 추측하지 않고 None

    def test_document_with_no_criteria_section_returns_empty_result(self):
        blocks = [
            DocumentBlock(
                block_id="b0",
                block_type=BlockType.TEXT,
                content="본 사업은 지역 소상공인의 디지털 전환을 지원하기 위해 추진한다.",
                location_type=LocationType.PAGE,
                location_number=1,
                order=0,
            ),
        ]
        extraction_result = DocumentExtractionResult(
            document_id="doc-notice-2",
            file_name="notice2.pdf",
            file_type=FileType.PDF,
            file_size=512,
            page_count=1,
            block_count=len(blocks),
            blocks=blocks,
        )
        context = ChunkSourceContext(
            document_id="doc-notice-2",
            source_type=SourceType.FILE_UPLOAD,
            source_filename="notice2.pdf",
        )
        chunking_result = chunk_document(extraction_result, context)

        stub = _CountingStub(response="{}")
        service = CriteriaExtractionService(llm_call=stub)
        request = CriteriaExtractionRequest(
            domain="government_support",
            notice_document_id="NOTICE-MOCK-GOV-002",
            chunks=chunking_result.chunks,
        )

        result = service.extract(request)

        assert stub.call_count == 0
        assert result.criteria == []
        assert result.meta.extraction_status == ExtractionStatus.NO_CANDIDATE_SECTION
