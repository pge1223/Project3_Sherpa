"""
Unified Document Parser
======================
파일 확장자에 따라 적절한 파서를 선택하는 래퍼
"""

import logging
import time
from pathlib import Path

from ai.rag.parsers.base_parser import BaseParser
from ai.rag.parsers.pdf_parser import PDFParser
from ai.rag.parsers.docx_parser import DOCXParser
from ai.rag.parsers.pptx_parser import PPTXParser
from ai.rag.parsers.hwpx_parser import HWPParser, HWPXParser
from ai.rag.parsers.schemas import DocumentExtractionResult, FileType
from ai.rag.parsers.exceptions import UnsupportedFormatError, FileSizeLimitExceededError


logger = logging.getLogger(__name__)

# 파일 크기 제한 (20MB)
MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024

# 확장자 → 파서 매핑
PARSER_MAP: dict[str, type[BaseParser]] = {
    "pdf": PDFParser,
    "docx": DOCXParser,
    "pptx": PPTXParser,
    "hwp": HWPParser,
    "hwpx": HWPXParser,
}


def extract_document(file_path: str | Path) -> DocumentExtractionResult:
    """
    문서 파일을 파싱하여 공통 형식의 결과 반환

    Args:
        file_path: 문서 파일 경로

    Returns:
        DocumentExtractionResult: 파싱 결과

    Raises:
        FileNotFoundError: 파일이 존재하지 않는 경우
        FileSizeLimitExceededError: 파일 크기가 20MB를 초과하는 경우
        UnsupportedFormatError: 지원하지 않는 파일 형식인 경우
        ParserError: 파싱 중 오류 발생
    """
    file_path = Path(file_path)

    # 파일 존재 확인
    if not file_path.exists():
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {file_path}")

    # 파일 크기 검사
    file_size = file_path.stat().st_size
    if file_size > MAX_FILE_SIZE_BYTES:
        raise FileSizeLimitExceededError(
            f"파일 크기가 제한({MAX_FILE_SIZE_BYTES // (1024*1024)}MB)을 초과합니다: {file_path.name} ({file_size // (1024*1024)}MB)"
        )

    # 확장자로 파서 선택
    extension = file_path.suffix.lower().lstrip(".")

    if extension not in PARSER_MAP:
        supported = ", ".join(PARSER_MAP.keys())
        raise UnsupportedFormatError(
            f"지원하지 않는 파일 형식입니다: .{extension}. 지원 형식: {supported}"
        )

    # 파서 인스턴스 생성 및 실행
    parser_class = PARSER_MAP[extension]
    parser = parser_class(file_path)

    logger.info(
        "[parse-start] file=%s extension=%s parser=%s file_size=%d",
        file_path.name, extension, parser_class.__name__, file_size,
    )
    started_at = time.perf_counter()
    try:
        result = parser.parse()
    except Exception:
        logger.exception(
            "[parse-failed] file=%s parser=%s elapsed_ms=%.1f",
            file_path.name, parser_class.__name__, (time.perf_counter() - started_at) * 1000,
        )
        raise
    logger.info(
        "[parse-done] file=%s parser=%s elapsed_ms=%.1f",
        file_path.name, parser_class.__name__, (time.perf_counter() - started_at) * 1000,
    )
    return result


def get_supported_formats() -> list[str]:
    """지원하는 파일 형식 목록 반환"""
    return list(PARSER_MAP.keys())
