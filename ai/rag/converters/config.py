"""
HWP/HWPX Conversion Configuration
=======================================
실행 파일 경로, 타임아웃, 임시 디렉터리 등 실행 설정. 값은 환경변수로 오버라이드할 수
있으며, 기준값을 코드 곳곳에 하드코딩하지 않는다.

지원 환경변수:
    HWP_CONVERSION_ENABLED               (기본 true)
    HWP_CONVERTER_EXECUTABLE             (기본: PATH에서 soffice/libreoffice 탐색)
    HWP_CONVERSION_TIMEOUT_SECONDS       (기본 60)
    HWP_CONVERSION_MAX_FILE_SIZE_BYTES   (기본 50MB)
    HWP_CONVERSION_KEEP_FILES            (기본 false)
    HWP_CONVERSION_TEMP_DIR              (기본: 시스템 임시 디렉터리)
"""

import os
import tempfile
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

DEFAULT_TIMEOUT_SECONDS: int = 60
DEFAULT_MAX_FILE_SIZE_BYTES: int = 50 * 1024 * 1024


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_str(name: str) -> Optional[str]:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return None
    return value


class HwpConversionConfig(BaseModel):
    """HWP/HWPX -> PDF 변환 실행 설정."""

    enabled: bool = Field(default_factory=lambda: _env_bool("HWP_CONVERSION_ENABLED", True))
    executable_path: Optional[str] = Field(default_factory=lambda: _env_str("HWP_CONVERTER_EXECUTABLE"))
    timeout_seconds: int = Field(
        default_factory=lambda: _env_int("HWP_CONVERSION_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)
    )
    max_file_size_bytes: int = Field(
        default_factory=lambda: _env_int("HWP_CONVERSION_MAX_FILE_SIZE_BYTES", DEFAULT_MAX_FILE_SIZE_BYTES)
    )
    keep_converted_files: bool = Field(default_factory=lambda: _env_bool("HWP_CONVERSION_KEEP_FILES", False))
    temp_dir: Optional[str] = Field(default_factory=lambda: _env_str("HWP_CONVERSION_TEMP_DIR"))

    def resolve_temp_dir(self) -> Path:
        if self.temp_dir:
            return Path(self.temp_dir)
        return Path(tempfile.gettempdir())


__all__ = [
    "HwpConversionConfig",
    "DEFAULT_TIMEOUT_SECONDS",
    "DEFAULT_MAX_FILE_SIZE_BYTES",
]
