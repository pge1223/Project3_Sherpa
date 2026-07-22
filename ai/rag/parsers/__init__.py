"""
Document Parsing Module
======================
PDF, DOCX, PPTX, HWP, HWPX 문서에서 텍스트를 추출하는 파서 모듈
이미지 OCR(EasyOCR)을 지원합니다.

사용 예시:
    from ai.rag.parsers import extract_document

    result = extract_document("document.pdf")
    for block in result.blocks:
        print(f"[P{block.page_number}] {block.content}")

OCR 사용 예시:
    from ai.rag.parsers import PDFParser
    from ai.rag.parsers.easyocr_engine import EasyOCR

    ocr = EasyOCR(languages=["ko", "en"])
    parser = PDFParser("document.pdf", ocr_engine=ocr)
    result = parser.parse()
"""

from ai.rag.parsers.base_parser import BaseParser
from ai.rag.parsers.base_ocr import BaseOCR, OCRResult
from ai.rag.parsers.pdf_parser import PDFParser
from ai.rag.parsers.docx_parser import DOCXParser
from ai.rag.parsers.pptx_parser import PPTXParser
from ai.rag.parsers.hwpx_parser import HWPParser, HWPXParser
from ai.rag.parsers.unified_parser import extract_document
from ai.rag.parsers.exceptions import (
    ParserError,
    EmptyDocumentError,
    CorruptedDocumentError,
    UnsupportedFormatError,
    FileSizeLimitExceededError,
)

__all__ = [
    # Base
    "BaseParser",
    "BaseOCR",
    "OCRResult",
    # Parsers
    "PDFParser",
    "DOCXParser",
    "PPTXParser",
    "HWPParser",
    "HWPXParser",
    "extract_document",
    # Exceptions
    "ParserError",
    "EmptyDocumentError",
    "CorruptedDocumentError",
    "UnsupportedFormatError",
    "FileSizeLimitExceededError",
]
