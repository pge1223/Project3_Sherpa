"""
Document Converter Factory
================================
확장자에 따라 변환이 필요한지 판단하고, 필요하면 적절한 변환기를 선택해 실행한다.
PDF/DOCX/PPTX는 변환 대상이 아니므로 이 모듈을 거치지 않고 기존 extract_document()로
바로 전달돼야 한다 — requires_conversion()이 False를 반환하는 확장자를 억지로 변환하지
않는다.
"""

import logging
from pathlib import Path
from typing import Optional

from ai.rag.converters.config import HwpConversionConfig
from ai.rag.converters.hwp_pdf_converter import SUPPORTED_EXTENSIONS, HwpPdfConverter
from ai.rag.converters.schemas import DocumentConversionResult

logger = logging.getLogger(__name__)


def requires_conversion(source_path: Path) -> bool:
    """이 확장자가 PDF 변환을 거쳐야만 기존 파서로 처리할 수 있는지 여부.
    현재는 HWP/HWPX만 해당하며, PDF/DOCX/PPTX는 항상 False."""
    return Path(source_path).suffix.lower() in SUPPORTED_EXTENSIONS


def get_converter_for(
    source_path: Path, config: Optional[HwpConversionConfig] = None
) -> Optional[HwpPdfConverter]:
    """source_path를 변환할 수 있는 변환기를 반환한다. 변환이 필요 없으면 None."""
    if not requires_conversion(source_path):
        return None
    return HwpPdfConverter(config=config)


def convert_if_needed(
    source_path: Path,
    *,
    output_dir: Optional[Path] = None,
    config: Optional[HwpConversionConfig] = None,
) -> Optional[DocumentConversionResult]:
    """PDF 변환이 필요한 형식이면 변환을 수행하고 결과를 반환한다.
    PDF/DOCX/PPTX 등 변환이 필요 없는 형식이면 None을 반환하며, 이 경우 호출자는
    원본 경로를 그대로 extract_document()에 전달하면 된다.

    변환 실패 시 DocumentConversionError 계열 예외를 그대로 전파한다 — 실패를
    삼키고 조용히 None을 반환하지 않는다(호출자가 conversion_status=failed 처리를
    할 수 있어야 하기 때문)."""
    converter = get_converter_for(source_path, config=config)
    if converter is None:
        return None
    return converter.convert(source_path, output_dir=output_dir)


def cleanup_converted_file(
    result: Optional[DocumentConversionResult],
    *,
    config: Optional[HwpConversionConfig] = None,
) -> None:
    """변환된 임시 PDF를 정리한다. keep_converted_files=True면 삭제하지 않는다.
    삭제 실패는 warning 로그만 남기고 예외를 던지지 않는다 — 색인 성공 여부에
    영향을 주지 않기 위함이다. 원본 파일(result.original_path)은 절대 삭제하지 않는다."""
    if result is None or not result.success:
        return

    effective_config = config or HwpConversionConfig()
    if effective_config.keep_converted_files:
        return

    converted_path = Path(result.converted_path)
    try:
        if converted_path.exists():
            converted_path.unlink()
    except OSError as exc:
        logger.warning(
            "[DOCUMENT_CONVERSION_CLEANUP_FAILED] path_name=%s error=%s",
            converted_path.name,
            exc,
        )


__all__ = [
    "requires_conversion",
    "get_converter_for",
    "convert_if_needed",
    "cleanup_converted_file",
]
