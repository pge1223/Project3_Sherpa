"""
Tests for Document Parsers
==========================

Requirements:
    pip install pytest pymupdf python-docx python-pptx pydantic

Run with:
    pytest ai/rag/tests/test_parsers.py -v
"""

import os
import sys
from pathlib import Path

import pytest

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from ai.rag.parsers import (
    extract_document,
    PDFParser,
    DOCXParser,
    PPTXParser,
    FileSizeLimitExceededError,
    UnsupportedFormatError,
    EmptyDocumentError,
    CorruptedDocumentError,
)
from ai.rag.parsers.schemas import FileType, LocationType, BlockType


class TestExtractDocument:
    """extract_document 함수 테스트"""

    def test_unsupported_format(self, txt_file: Path):
        """지원하지 않는 형식 → UnsupportedFormatError"""
        if not txt_file.exists():
            pytest.skip(f"Test fixture not found: {txt_file}")

        with pytest.raises(UnsupportedFormatError):
            extract_document(txt_file)

    def test_nonexistent_file(self):
        """존재하지 않는 파일 → FileNotFoundError"""
        with pytest.raises(FileNotFoundError):
            extract_document("nonexistent_file.pdf")


class TestPDFParser:
    """PDF 파서 테스트"""

    def test_parse_pdf_success(self, sample_pdf: Path):
        """PDF 정상 파싱"""
        if not sample_pdf.exists():
            pytest.skip(f"Test fixture not found: {sample_pdf}")

        result = extract_document(sample_pdf)

        assert result.file_name == "sample.pdf"
        assert result.file_type == FileType.PDF
        assert result.page_count is not None
        assert result.page_count > 0
        assert result.block_count > 0
        assert result.blocks is not None

        # 페이지 번호 확인
        for block in result.blocks:
            assert block.location_type == LocationType.PAGE
            assert block.location_number is not None
            assert 1 <= block.location_number <= result.page_count

        # 블록 ID 일관성 확인
        block_ids = [b.block_id for b in result.blocks]
        assert len(block_ids) == len(set(block_ids)), "중복된 block_id가 있습니다"

    def test_parse_empty_pdf(self, empty_pdf: Path):
        """빈 PDF → EmptyDocumentError"""
        if not empty_pdf.exists():
            pytest.skip(f"Test fixture not found: {empty_pdf}")

        with pytest.raises(EmptyDocumentError):
            extract_document(empty_pdf)

    def test_parse_corrupted_pdf(self, corrupted_file: Path):
        """손상된 PDF → CorruptedDocumentError"""
        if not corrupted_file.exists():
            pytest.skip(f"Test fixture not found: {corrupted_file}")

        with pytest.raises(CorruptedDocumentError):
            extract_document(corrupted_file)


class TestDOCXParser:
    """DOCX 파서 테스트"""

    def test_parse_docx_success(self, sample_docx: Path):
        """DOCX 정상 파싱"""
        if not sample_docx.exists():
            pytest.skip(f"Test fixture not found: {sample_docx}")

        result = extract_document(sample_docx)

        assert result.file_name == "sample.docx"
        assert result.file_type == FileType.DOCX
        assert result.block_count > 0
        assert result.blocks is not None

        # DOCX는 DOCUMENT 위치 유형
        for block in result.blocks:
            assert block.location_type == LocationType.DOCUMENT
            assert block.location_number is None

        # 블록 ID 일관성 확인
        block_ids = [b.block_id for b in result.blocks]
        assert len(block_ids) == len(set(block_ids)), "중복된 block_id가 있습니다"

    def test_docx_table_detection(self, sample_docx: Path):
        """DOCX 표 감지"""
        if not sample_docx.exists():
            pytest.skip(f"Test fixture not found: {sample_docx}")

        result = extract_document(sample_docx)

        # 표가 있는 경우
        table_blocks = [b for b in result.blocks if b.block_type == BlockType.TABLE]
        if table_blocks:
            for table in table_blocks:
                assert "\t" in table.content, "표가 탭 구분자로 변환되어야 합니다"


class TestPPTXParser:
    """PPTX 파서 테스트"""

    def test_parse_pptx_success(self, sample_pptx: Path):
        """PPTX 정상 파싱"""
        if not sample_pptx.exists():
            pytest.skip(f"Test fixture not found: {sample_pptx}")

        result = extract_document(sample_pptx)

        assert result.file_name == "sample.pptx"
        assert result.file_type == FileType.PPTX
        assert result.page_count is not None
        assert result.page_count > 0
        assert result.block_count > 0
        assert result.blocks is not None

        # 슬라이드 번호 확인
        for block in result.blocks:
            assert block.location_type == LocationType.SLIDE
            assert block.location_number is not None
            assert 1 <= block.location_number <= result.page_count

        # 블록 ID 일관성 확인
        block_ids = [b.block_id for b in result.blocks]
        assert len(block_ids) == len(set(block_ids)), "중복된 block_id가 있습니다"

    def test_pptx_slide_order(self, sample_pptx: Path):
        """PPTX 슬라이드 순서 유지"""
        if not sample_pptx.exists():
            pytest.skip(f"Test fixture not found: {sample_pptx}")

        result = extract_document(sample_pptx)

        # order 순서대로 정렬되어야 함
        orders = [b.order for b in result.blocks]
        assert orders == sorted(orders), "블록이 순서대로 정렬되어야 합니다"


class TestBlockIDDeterminism:
    """블록 ID 결정론 테스트"""

    def test_same_file_same_ids(self, sample_pdf: Path):
        """동일 파일을 두 번 파싱하면 같은 block_id"""
        if not sample_pdf.exists():
            pytest.skip(f"Test fixture not found: {sample_pdf}")

        result1 = extract_document(sample_pdf)
        result2 = extract_document(sample_pdf)

        assert len(result1.blocks) == len(result2.blocks)

        for b1, b2 in zip(result1.blocks, result2.blocks):
            assert b1.block_id == b2.block_id, "동일 파일에서 생성된 block_id가 같아야 합니다"


class TestScannedPDFDetection:
    """스캔 PDF 탐지 테스트"""

    def test_requires_ocr_warning(self, sample_pdf: Path):
        """스캔 PDF 경고 확인"""
        if not sample_pdf.exists():
            pytest.skip(f"Test fixture not found: {sample_pdf}")

        result = extract_document(sample_pdf)

        # 스캔 PDF로 판단되면 requires_ocr이 True
        if result.is_scanned_pdf:
            assert result.requires_ocr is True
            assert any("OCR" in w or "스캔" in w for w in result.warnings)


class TestFileSizeLimit:
    """파일 크기 제한 테스트"""

    def test_large_file_rejection(self, large_file: Path):
        """20MB 초과 파일 거부"""
        if not large_file.exists():
            pytest.skip(f"Test fixture not found: {large_file}")

        # 실제 파일 크기 확인
        file_size = large_file.stat().st_size

        if file_size > 20 * 1024 * 1024:
            with pytest.raises(FileSizeLimitExceededError):
                extract_document(large_file)
        else:
            pytest.skip("테스트 파일이 20MB 이하입니다")


# 테스트 실행 확인용
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
