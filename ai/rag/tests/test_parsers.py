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


class TestOCRService:
    """OCR 서비스 테스트"""

    def test_ocr_engine_import(self):
        """OCR 모듈 import 가능"""
        try:
            from ai.rag.parsers.base_ocr import BaseOCR
            from ai.rag.parsers.easyocr_engine import EasyOCR
            from ai.rag.parsers import BaseOCR, OCRResult
            assert True
        except ImportError:
            pytest.skip("OCR 종속성 설치 필요")

    def test_ocr_result_dataclass(self):
        """OCRResult 데이터 클래스 테스트"""
        if self._is_ocr_available(raise_skip=False):
            from ai.rag.parsers.base_ocr import OCRResult
            result = OCRResult(text="테스트", confidence=0.95)
            assert result.text == "테스트"
            assert result.confidence == 0.95
            assert result.bounding_boxes is None

    def test_easyocr_initialization(self, ocr_engine):
        """EasyOCR 초기화 테스트"""
        if ocr_engine is None:
            pytest.skip("EasyOCR 설치 필요")

        assert ocr_engine.name == "EasyOCR"
        assert "ko" in ocr_engine.supported_languages
        assert "en" in ocr_engine.supported_languages

    def _is_ocr_available(self, raise_skip: bool = True):
        """OCR가 사용 가능한지 확인"""
        try:
            from ai.rag.parsers.easyocr_engine import EasyOCR
            ocr = EasyOCR(languages=["ko", "en"], gpu=False)
            if ocr.is_available():
                return True
            if raise_skip:
                pytest.skip("EasyOCR 설치 및 모델 다운로드 필요")
            return False
        except ImportError:
            if raise_skip:
                pytest.skip("EasyOCR 설치 필요: pip install easyocr")
            return False


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


class TestPDFParserOCR:
    """PDF 파서 OCR 통합 테스트"""

    def test_pdf_parser_with_ocr_disabled(self, sample_pdf: Path):
        """OCR 비활성화 상태로 PDF 파싱"""
        if not sample_pdf.exists():
            pytest.skip(f"Test fixture not found: {sample_pdf}")

        from ai.rag.parsers import PDFParser

        parser = PDFParser(str(sample_pdf), enable_ocr=False)
        result = parser.parse()

        assert result.file_type == FileType.PDF
        assert result.block_count > 0

    def test_pdf_parser_ocr_engine_property(self, sample_pdf: Path):
        """PDFParser OCR 엔진 프로퍼티 테스트"""
        if not sample_pdf.exists():
            pytest.skip(f"Test fixture not found: {sample_pdf}")

        from ai.rag.parsers import PDFParser

        parser = PDFParser(str(sample_pdf))

        # OCR 비활성화 시 None 반환
        parser_disabled = PDFParser(str(sample_pdf), enable_ocr=False)
        assert parser_disabled.ocr_engine is None

    def test_pdf_parser_with_custom_ocr_engine(self, sample_pdf: Path, ocr_engine):
        """커스텀 OCR 엔진으로 PDF 파싱"""
        if not sample_pdf.exists():
            pytest.skip(f"Test fixture not found: {sample_pdf}")
        if ocr_engine is None:
            pytest.skip("EasyOCR 설치 필요")

        from ai.rag.parsers import PDFParser

        parser = PDFParser(str(sample_pdf), ocr_engine=ocr_engine)
        assert parser.is_ocr_available() is True

        result = parser.parse()
        assert result.block_count > 0


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
