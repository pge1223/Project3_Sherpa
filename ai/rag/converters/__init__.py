"""
Document Converters (HWP/HWPX -> PDF)
===========================================
HWP/HWPX 문서를 기존 PDF 파서(ai.rag.parsers)가 처리할 수 있는 내부 처리용 PDF로
변환한다. PDF/DOCX/PPTX는 이 패키지를 거치지 않고 기존 경로를 그대로 사용한다.
"""

from ai.rag.converters.base import DocumentConverter
from ai.rag.converters.config import HwpConversionConfig
from ai.rag.converters.exceptions import (
    ConversionProcessError,
    ConversionTimeoutError,
    ConverterUnavailableError,
    ConvertedFileNotFoundError,
    DocumentConversionError,
    InvalidConvertedPdfError,
    InvalidSourceFileError,
    SourceFileTooLargeError,
    UnsupportedConversionFormatError,
)
from ai.rag.converters.factory import (
    cleanup_converted_file,
    convert_if_needed,
    get_converter_for,
    requires_conversion,
)
from ai.rag.converters.hwp_pdf_converter import (
    SUPPORTED_EXTENSIONS,
    HwpPdfConverter,
    find_executable,
    looks_like_hwp,
    looks_like_hwpx,
)
from ai.rag.converters.schemas import (
    ConversionStatus,
    DocumentConversionMetadata,
    DocumentConversionResult,
    build_conversion_metadata,
)

__all__ = [
    "DocumentConverter",
    "HwpConversionConfig",
    "HwpPdfConverter",
    "SUPPORTED_EXTENSIONS",
    "find_executable",
    "looks_like_hwp",
    "looks_like_hwpx",
    "requires_conversion",
    "get_converter_for",
    "convert_if_needed",
    "cleanup_converted_file",
    "ConversionStatus",
    "DocumentConversionResult",
    "DocumentConversionMetadata",
    "build_conversion_metadata",
    "DocumentConversionError",
    "ConverterUnavailableError",
    "UnsupportedConversionFormatError",
    "ConversionTimeoutError",
    "ConversionProcessError",
    "ConvertedFileNotFoundError",
    "InvalidConvertedPdfError",
    "InvalidSourceFileError",
    "SourceFileTooLargeError",
]
