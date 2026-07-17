"""
Document Converter Protocol
=================================
"""

from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

from ai.rag.converters.schemas import DocumentConversionResult


@runtime_checkable
class DocumentConverter(Protocol):
    """확장자에 따라 원본 문서를 내부 처리용 PDF로 변환하는 변환기의 공통 인터페이스."""

    def supports(self, source_path: Path) -> bool:
        """이 변환기가 source_path의 확장자를 변환 대상으로 다루는지 여부."""
        ...

    def convert(
        self,
        source_path: Path,
        *,
        output_dir: Optional[Path] = None,
    ) -> DocumentConversionResult:
        """source_path를 PDF로 변환한다. 실패 시 DocumentConversionError 계열 예외를 던진다."""
        ...


__all__ = ["DocumentConverter"]
