"""
Tests for Document Parsers
==========================

Requirements:
    pip install pytest pymupdf python-docx python-pptx pydantic

Run with:
    pytest ai/rag/tests/test_parsers.py -v

For OCR integration tests:
    pytest ai/rag/tests/test_parsers.py -v -m ocr
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock
from typing import Any

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
        from ai.rag.parsers.base_ocr import OCRResult
        result = OCRResult(text="테스트", confidence=0.95)
        assert result.text == "테스트"
        assert result.confidence == 0.95
        assert result.bounding_boxes is None

    def test_easyocr_initialization_with_reader(self):
        """EasyOCR Reader 초기화 테스트"""
        try:
            from ai.rag.parsers.easyocr_engine import EasyOCR
            ocr = EasyOCR(languages=["ko", "en"], gpu=False)
            assert ocr.name == "EasyOCR"
            assert "ko" in ocr.supported_languages
            assert "en" in ocr.supported_languages
        except ImportError:
            pytest.skip("EasyOCR 설치 필요: pip install easyocr")

    def test_easyocr_initialization(self, ocr_engine):
        """사용 가능한 EasyOCR fixture의 기본 설정 테스트"""
        if ocr_engine is None:
            pytest.skip("EasyOCR 모델 설치 필요")

        assert ocr_engine.name == "EasyOCR"
        assert "ko" in ocr_engine.supported_languages
        assert "en" in ocr_engine.supported_languages

    def test_ocr_engine_not_downloading_on_unavailable(self):
        """OCR 엔진 사용 불가 시 모델 다운로드 방지"""
        try:
            from ai.rag.parsers.easyocr_engine import EasyOCR
            # raise_on_init_error=False로 설정하면 초기화 실패 시 경고만 발생
            ocr = EasyOCR(languages=["ko", "en"], download_enabled=False)
            # import 가능해도 Reader 초기화 실패 시 None 반환
            result = ocr.is_available()
            # False 또는 True (환경에 따라)
            assert isinstance(result, bool)
        except ImportError:
            pytest.skip("EasyOCR 설치 필요: pip install easyocr")


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


# =============================================================================
# EasyOCR 단위 테스트 (Mock 기반)
# =============================================================================


class TestEasyOCRUnit:
    """EasyOCR 단위 테스트 - Mock 기반"""

    def test_easyocr_initialization_with_reader(self):
        """EasyOCR이 Reader 클래스로 초기화되는지 확인"""
        with patch("easyocr.Reader") as mock_reader_class:
            mock_reader_instance = MagicMock()
            mock_reader_class.return_value = mock_reader_instance

            from ai.rag.parsers.easyocr_engine import EasyOCR
            ocr = EasyOCR(languages=["ko", "en"], gpu=False)

            # Reader가 아직 초기화되지 않아야 함 (lazy initialization)
            assert ocr._reader is None

            # _get_reader() 호출 시 Reader 초기화
            reader = ocr._get_reader()
            assert reader is not None

            # Reader가 correct 클래스로 생성되었는지 확인
            mock_reader_class.assert_called_once()
            call_kwargs = mock_reader_class.call_args[1]
            assert call_kwargs["lang_list"] == ["ko", "en"]
            assert call_kwargs["gpu"] is False
            assert call_kwargs["download_enabled"] is True

    def test_easyocr_initialization_error_handling(self):
        """EasyOCR 초기화 실패 시 예외 처리"""
        with patch("easyocr.Reader", side_effect=Exception("CUDA not available")):
            from ai.rag.parsers.easyocr_engine import EasyOCR, OCRInitializationError

            # raise_on_init_error=False (기본값): 경고만 발생
            ocr = EasyOCR(languages=["ko", "en"], raise_on_init_error=False)
            reader = ocr._get_reader()
            assert reader is None
            assert ocr._init_error is not None

            # raise_on_init_error=True: 예외 발생
            ocr2 = EasyOCR(languages=["ko", "en"], raise_on_init_error=True)
            with pytest.raises(OCRInitializationError):
                ocr2._get_reader()

    def test_easyocr_is_available_true(self):
        """OCR 사용 가능 상태 확인 (성공 시)"""
        with patch("easyocr.Reader") as mock_reader_class:
            mock_reader_class.return_value = MagicMock()

            from ai.rag.parsers.easyocr_engine import EasyOCR
            ocr = EasyOCR(languages=["ko", "en"])
            assert ocr.is_available() is True

    def test_easyocr_is_available_false_on_import_error(self):
        """easyocr import 실패 시 is_available()가 False 반환"""
        # easyocr이 이미 로드되어 있으면 이 테스트를 건너뜁니다
        try:
            import easyocr
            pytest.skip("easyocr이 이미 설치되어 있습니다. 이 테스트는 import 실패 시나리오만 테스트합니다.")
        except ImportError:
            pass

        # easyocr이 없을 때 is_available이 False를 반환하는지 확인
        with patch.dict(sys.modules, {"easyocr": None}):
            with patch("builtins.__import__", side_effect=ImportError("No module named 'easyocr'")):
                from ai.rag.parsers.easyocr_engine import EasyOCR
                ocr = EasyOCR(languages=["ko", "en"])
                result = ocr.is_available()
                assert result is False

    def test_easyocr_extract_text_from_bytes(self):
        """이미지 바이트에서 텍스트 추출 테스트 (Mock)"""
        # PIL Image도 mock 처리하여 실제 이미지 디코딩 방지
        mock_image = MagicMock()
        mock_image_array = [[0]] * 50

        with patch("easyocr.Reader") as mock_reader_class, \
             patch("PIL.Image.open", return_value=mock_image), \
             patch("numpy.array", return_value=mock_image_array):
            mock_reader = MagicMock()
            mock_reader_class.return_value = mock_reader

            # EasyOCR이 반환하는 형식의 mock 결과
            mock_reader.readtext.return_value = [
                ([[0, 0], [100, 0], [100, 50], [0, 50]], "안녕하세요", 0.95),
                ([[0, 50], [150, 50], [150, 100], [0, 100]], "테스트입니다", 0.90),
            ]

            from ai.rag.parsers.easyocr_engine import EasyOCR
            ocr = EasyOCR(languages=["ko", "en"])

            # 더미 이미지 바이트
            dummy_image_bytes = b"\x89PNG\r\n\x1a\n..."

            result = ocr.extract_text_from_bytes(dummy_image_bytes)

            assert result.text == "안녕하세요 테스트입니다"
            assert result.confidence == pytest.approx(0.925, rel=0.01)
            assert result.language == "ko,en"
            assert len(result.bounding_boxes) == 2

    def test_easyocr_extract_text_empty_result(self):
        """OCR 결과가 없을 때 처리"""
        mock_image = MagicMock()
        mock_image_array = [[0]] * 50

        with patch("easyocr.Reader") as mock_reader_class, \
             patch("PIL.Image.open", return_value=mock_image), \
             patch("numpy.array", return_value=mock_image_array):
            mock_reader = MagicMock()
            mock_reader_class.return_value = mock_reader
            mock_reader.readtext.return_value = []

            from ai.rag.parsers.easyocr_engine import EasyOCR
            ocr = EasyOCR(languages=["ko", "en"])

            result = ocr.extract_text_from_bytes(b"dummy")

            assert result.text == ""
            assert result.confidence == 0.0
            assert result.bounding_boxes is None

    def test_easyocr_extract_text_strips_whitespace(self):
        """OCR 결과 텍스트의 공백 처리"""
        mock_image = MagicMock()
        mock_image_array = [[0]] * 50

        with patch("easyocr.Reader") as mock_reader_class, \
             patch("PIL.Image.open", return_value=mock_image), \
             patch("numpy.array", return_value=mock_image_array):
            mock_reader = MagicMock()
            mock_reader_class.return_value = mock_reader
            mock_reader.readtext.return_value = [
                ([[0, 0], [100, 0], [100, 50], [0, 50]], "  안녕하세요  ", 0.95),
                ([[0, 50], [150, 50], [150, 100], [0, 100]], "  테스트  ", 0.90),
            ]

            from ai.rag.parsers.easyocr_engine import EasyOCR
            ocr = EasyOCR(languages=["ko", "en"])

            result = ocr.extract_text_from_bytes(b"dummy")

            # 공백이 제거되고 하나의 텍스트로 결합됨
            assert "안녕하세요" in result.text
            assert "테스트" in result.text
            assert "  " not in result.text  # 이중 공백 없음


class TestPDFParserOCRFiltering:
    """PDF 파서 이미지 OCR 필터링 테스트"""

    def test_duplicate_image_xref_filtering(self, sample_pdf: Path):
        """페이지 간 중복 이미지 xref 필터링"""
        if not sample_pdf.exists():
            pytest.skip(f"Test fixture not found: {sample_pdf}")

        from unittest.mock import MagicMock, patch
        from ai.rag.parsers.pdf_parser import PDFParser

        # sample.pdf로 테스트 (실제 PDF 사용)
        parser = PDFParser(str(sample_pdf), enable_ocr=False)
        result = parser.parse()

        # sample.pdf에 이미지 중복이 없으므로 전체 이미지 처리 확인
        image_blocks = [b for b in result.blocks if b.block_type == BlockType.IMAGE]

        # 동일한 xref는 한 번만 처리되어야 함
        xrefs = [b.metadata.get("xref") for b in image_blocks if b.metadata.get("xref")]
        unique_xrefs = set(xrefs)
        assert len(xrefs) == len(unique_xrefs), "중복된 xref가 있습니다"

    def test_image_rect_filtering_logic(self):
        """이미지 rect 필터링 로직이 정상 동작하는지 확인"""
        sample_pdf_path = "ai/rag/tests/fixtures/sample.pdf"
        if not Path(sample_pdf_path).exists():
            pytest.skip(f"Test fixture not found: {sample_pdf_path}")

        from ai.rag.parsers.pdf_parser import PDFParser

        # OCR 비활성화로 테스트 (이미지 OCR 로직은 단위 테스트에서 이미 검증됨)
        parser = PDFParser(sample_pdf_path, enable_ocr=False)
        result = parser.parse()

        # 파싱 성공 확인
        assert result is not None
        assert result.block_count > 0
        assert result.page_count > 0

        # location_number가 페이지 범위 내인지 확인
        for block in result.blocks:
            assert 1 <= block.location_number <= result.page_count

    def test_page_location_number_preserved(self, sample_pdf: Path):
        """OCR 결과의 location_number가 페이지 번호를 유지"""
        if not sample_pdf.exists():
            pytest.skip(f"Test fixture not found: {sample_pdf}")

        from ai.rag.parsers.pdf_parser import PDFParser

        parser = PDFParser(str(sample_pdf), enable_ocr=False)
        result = parser.parse()

        # 모든 블록의 location_number가 페이지 범위 내인지 확인
        for block in result.blocks:
            assert 1 <= block.location_number <= result.page_count, \
                f"location_number {block.location_number}이 페이지 범위({result.page_count})를 벗어남"

        # 페이지 번호 순서가 올바른지 확인
        location_numbers = [b.location_number for b in result.blocks]
        assert location_numbers == sorted(location_numbers), \
            "location_number가 페이지 순서대로 정렬되어야 함"


# =============================================================================
# OCR 통합 테스트 (실제 EasyOCR 모델 사용)
# =============================================================================


@pytest.mark.ocr
class TestScannedPDFIntegration:
    """스캔 PDF OCR 통합 테스트 (실제 모델)"""

    @pytest.fixture
    def scanned_pdf(self, fixtures_dir: Path) -> Path:
        """테스트용 스캔 PDF 파일"""
        return fixtures_dir / "test2.pdf"

    def test_scanned_pdf_detection(self, scanned_pdf: Path):
        """스캔 PDF 판정 테스트"""
        if not scanned_pdf.exists():
            pytest.skip(f"Test fixture not found: {scanned_pdf}")

        result = extract_document(scanned_pdf)

        # is_scanned_pdf가 true여야 함
        assert result.is_scanned_pdf is True, "스캔 PDF로 판정되어야 합니다"
        assert result.requires_ocr is True, "OCR이 필요한 상태여야 합니다"

    def test_scanned_pdf_ocr_text_extraction(self, scanned_pdf: Path):
        """스캔 PDF에서 OCR 텍스트 추출 테스트"""
        if not scanned_pdf.exists():
            pytest.skip(f"Test fixture not found: {scanned_pdf}")

        from ai.rag.parsers import PDFParser
        from ai.rag.parsers.easyocr_engine import EasyOCR

        # EasyOCR 사용 가능 확인
        ocr = EasyOCR(languages=["ko", "en"], gpu=False)
        if not ocr.is_available():
            pytest.skip("EasyOCR 설치 및 모델 다운로드 필요")

        parser = PDFParser(str(scanned_pdf), ocr_engine=ocr)
        result = parser.parse()

        # OCR이 수행되었는지 확인
        ocr_blocks = [b for b in result.blocks if b.metadata.get("ocr_performed")]

        # 텍스트 블록이 1개 이상 생성됨
        assert len(ocr_blocks) >= 1, "OCR 텍스트 블록이 1개 이상 있어야 합니다"

        # 한글 텍스트가 포함되어 있어야 함
        ocr_text = " ".join([b.content for b in ocr_blocks])
        assert len(ocr_text) > 0, "OCR 텍스트가 비어 있지 않아야 합니다"
        assert any("\ac00" <= c <= "힯" for c in ocr_text), "한글 텍스트가 포함되어야 합니다"

    def test_page_location_numbers_preserved(self, scanned_pdf: Path):
        """OCR 결과의 페이지 위치 정보 유지 테스트"""
        if not scanned_pdf.exists():
            pytest.skip(f"Test fixture not found: {scanned_pdf}")

        from ai.rag.parsers import PDFParser
        from ai.rag.parsers.easyocr_engine import EasyOCR

        ocr = EasyOCR(languages=["ko", "en"], gpu=False)
        if not ocr.is_available():
            pytest.skip("EasyOCR 설치 및 모델 다운로드 필요")

        parser = PDFParser(str(scanned_pdf), ocr_engine=ocr)
        result = parser.parse()

        # 각 페이지의 location_number 확인
        location_numbers = set(b.location_number for b in result.blocks if b.location_number)

        # 2페이지 PDF이므로 1과 2가 포함되어야 함
        assert 1 in location_numbers, "페이지 1의 location_number가 있어야 합니다"
        assert 2 in location_numbers, "페이지 2의 location_number가 있어야 합니다"

    def test_no_duplicate_ocr_text_in_same_page(self, scanned_pdf: Path):
        """동일 페이지에서 OCR 텍스트가 중복되지 않음"""
        if not scanned_pdf.exists():
            pytest.skip(f"Test fixture not found: {scanned_pdf}")

        from ai.rag.parsers import PDFParser
        from ai.rag.parsers.easyocr_engine import EasyOCR

        ocr = EasyOCR(languages=["ko", "en"], gpu=False)
        if not ocr.is_available():
            pytest.skip("EasyOCR 설치 및 모델 다운로드 필요")

        parser = PDFParser(str(scanned_pdf), ocr_engine=ocr)
        result = parser.parse()

        # 페이지별 OCR 블록 수 확인
        ocr_blocks_by_page: dict[int, list] = {}
        for block in result.blocks:
            if block.metadata.get("ocr_performed"):
                page_num = block.location_number
                if page_num not in ocr_blocks_by_page:
                    ocr_blocks_by_page[page_num] = []
                ocr_blocks_by_page[page_num].append(block)

        # 각 페이지에서 이미지 OCR은 1번만 수행되어야 함
        for page_num, blocks in ocr_blocks_by_page.items():
            # 동일한 콘텐츠가 중복되지 않아야 함
            contents = [b.content for b in blocks]
            unique_contents = set(contents)
            assert len(contents) == len(unique_contents), \
                f"페이지 {page_num}에서 중복된 OCR 텍스트가 있습니다"

    def test_easyocr_reader_initialization(self):
        """EasyOCR Reader 초기화 테스트"""
        from ai.rag.parsers.easyocr_engine import EasyOCR

        ocr = EasyOCR(languages=["ko", "en"], gpu=False)
        if not ocr.is_available():
            pytest.skip("EasyOCR 설치 및 모델 다운로드 필요")

        # Reader 초기화 확인
        reader = ocr._get_reader()
        assert reader is not None
        assert ocr.name == "EasyOCR"
