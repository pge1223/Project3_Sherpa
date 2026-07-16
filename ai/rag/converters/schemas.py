"""
Pydantic Schemas for Document Conversion (HWP/HWPX -> PDF)
================================================================
"""

from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, field_serializer


class ConversionStatus(str, Enum):
    """문서 변환 상태. PDF/DOCX/PPTX처럼 변환이 필요 없는 형식은 NOT_REQUIRED."""

    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    CONVERTING = "converting"
    COMPLETED = "completed"
    FAILED = "failed"


class DocumentConversionResult(BaseModel):
    """DocumentConverter.convert()의 반환값."""

    original_path: Path
    converted_path: Path

    original_file_type: str
    converted_file_type: str = "pdf"

    success: bool
    converter_name: str

    duration_ms: Optional[int] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None

    model_config = {"arbitrary_types_allowed": True}

    @field_serializer("original_path", "converted_path")
    def _serialize_path(self, value: Path) -> str:
        return str(value)


class DocumentConversionMetadata(BaseModel):
    """문서 모델/metadata dict에 그대로 저장할 수 있는 변환 정보.
    새 DB 컬럼을 추가하지 않고 기존 metadata dict 구조를 활용하는 것을 전제로 한다."""

    original_file_type: str
    processing_file_type: str
    conversion_status: ConversionStatus
    conversion_error: Optional[str] = None
    converter_name: Optional[str] = None
    conversion_duration_ms: Optional[int] = None


def build_conversion_metadata(result: DocumentConversionResult) -> DocumentConversionMetadata:
    """변환 결과를 문서 metadata에 저장할 형태로 변환한다."""
    return DocumentConversionMetadata(
        original_file_type=result.original_file_type,
        processing_file_type=result.converted_file_type,
        conversion_status=ConversionStatus.COMPLETED if result.success else ConversionStatus.FAILED,
        conversion_error=result.error_message,
        converter_name=result.converter_name,
        conversion_duration_ms=result.duration_ms,
    )


__all__ = [
    "ConversionStatus",
    "DocumentConversionResult",
    "DocumentConversionMetadata",
    "build_conversion_metadata",
]
