"""
HWP/HWPX Conversion Configuration
=======================================
실행 파일 경로, 타임아웃, 임시 디렉터리 등 실행 설정. 값은 환경변수로 오버라이드할 수
있으며, 기준값을 코드 곳곳에 하드코딩하지 않는다.

지원 환경변수 (우선순위 1 > 2 > 3 > 4):
    1. 실제 OS/프로세스 환경변수
    2. backend/.env
    3. 레포 루트 .env
    4. 코드 기본값

    HWP_CONVERSION_ENABLED               (기본 true)
    HWP_CONVERTER_EXECUTABLE             (기본: PATH에서 soffice/libreoffice 탐색)
    HWP_CONVERSION_TIMEOUT_SECONDS       (기본 60)
    HWP_CONVERSION_MAX_FILE_SIZE_BYTES   (기본 50MB)
    HWP_CONVERSION_KEEP_FILES            (기본 false)
    HWP_CONVERSION_TEMP_DIR              (기본: 시스템 임시 디렉터리)

설계 노트: backend/app/config.py의 pydantic-settings(BaseSettings)는 backend/.env를
자체 Settings 인스턴스로만 읽어들이고 os.environ에는 반영하지 않는다. 과거 이 모듈은
import 시점에 load_dotenv()로 os.environ 전체를 채워 넣어 문제를 우회했지만, 그 방식은
MongoDB/OpenAI 키처럼 HWP와 무관한 값까지 전역 환경에 주입하고, import 순서에 따라
결과가 달라질 수 있어 제거했다. 대신 이 모듈은 dotenv_values()로 파일을 "읽기만" 하고
(os.environ 변경 없음), HWP_* 6개 키만 골라 매 인스턴스 생성 시점에 계산한다.
"""

import os
import tempfile
from pathlib import Path
from typing import Optional, Sequence

from dotenv import dotenv_values
from pydantic import BaseModel

DEFAULT_TIMEOUT_SECONDS: int = 60
DEFAULT_MAX_FILE_SIZE_BYTES: int = 50 * 1024 * 1024

_ENV_KEY_ENABLED = "HWP_CONVERSION_ENABLED"
_ENV_KEY_EXECUTABLE = "HWP_CONVERTER_EXECUTABLE"
_ENV_KEY_TIMEOUT = "HWP_CONVERSION_TIMEOUT_SECONDS"
_ENV_KEY_MAX_SIZE = "HWP_CONVERSION_MAX_FILE_SIZE_BYTES"
_ENV_KEY_KEEP_FILES = "HWP_CONVERSION_KEEP_FILES"
_ENV_KEY_TEMP_DIR = "HWP_CONVERSION_TEMP_DIR"

# 이 모듈이 os.environ 밖에서 "읽기 전용"으로 취급하는 키 전체 — dotenv 파일에 다른 키
# (MONGODB_URL, OPENAI_API_KEY 등)가 섞여 있어도 이 목록에 없으면 절대 사용하지 않는다.
_HWP_ENV_KEYS: tuple[str, ...] = (
    _ENV_KEY_ENABLED,
    _ENV_KEY_EXECUTABLE,
    _ENV_KEY_TIMEOUT,
    _ENV_KEY_MAX_SIZE,
    _ENV_KEY_KEEP_FILES,
    _ENV_KEY_TEMP_DIR,
)


def _repo_root() -> Path:
    # ai/rag/converters/config.py -> parents[3] == 레포 루트
    return Path(__file__).resolve().parents[3]


def default_env_files() -> tuple[Path, ...]:
    """우선순위가 높은 순서로: backend/.env, 레포 루트 .env."""
    root = _repo_root()
    return (root / "backend" / ".env", root / ".env")


def resolve_hwp_env_settings(env_files: Optional[Sequence[Path]] = None) -> dict[str, str]:
    """OS 환경변수 > env_files(앞에 올수록 우선) > (없음) 순으로 HWP_* 6개 키만 병합한다.

    os.environ은 절대 읽기 외에 변경하지 않는다(파일 로딩은 dotenv_values로만 수행 —
    load_dotenv와 달리 반환값이 dict일 뿐 전역 상태에 부작용이 없다). 값이 빈 문자열이면
    "미설정"으로 취급해 다음 우선순위로 넘어간다.
    """
    paths = tuple(env_files) if env_files is not None else default_env_files()

    merged: dict[str, str] = {}
    # 파일 우선순위는 앞이 높으므로, 낮은 것부터 채우고 높은 것으로 덮어쓴다.
    for path in reversed(paths):
        path = Path(path)
        if not path.exists():
            continue
        file_values = dotenv_values(path)
        for key in _HWP_ENV_KEYS:
            value = file_values.get(key)
            if value is not None and value.strip() != "":
                merged[key] = value

    # 실제 OS/프로세스 환경변수가 dotenv 파일보다 항상 우선한다.
    for key in _HWP_ENV_KEYS:
        value = os.environ.get(key)
        if value is not None and value.strip() != "":
            merged[key] = value

    return merged


def _parse_bool(value: Optional[str], default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_int(value: Optional[str], default: int) -> int:
    """정수로 파싱 실패 시(잘못된 값) 조용히 기본값으로 폴백한다 — 기존 동작 유지."""
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


class HwpConversionConfig(BaseModel):
    """HWP/HWPX -> PDF 변환 실행 설정.

    `HwpConversionConfig()`처럼 인자 없이 생성하면 resolve_hwp_env_settings()로 계산한
    값이 필드 기본값으로 쓰인다. 특정 필드를 명시적으로 넘기면(`HwpConversionConfig(enabled=True)`)
    그 값이 그대로 쓰이고 나머지 필드만 환경에서 채워진다 — 기존 호출부/테스트 호환.

    `env_files`는 생성자 전용 키워드로, pydantic 필드가 아니다(테스트에서 임시 dotenv
    경로를 주입하기 위한 용도). 생략하면 default_env_files()(backend/.env, 레포 루트 .env)를 쓴다.
    """

    enabled: bool
    executable_path: Optional[str]
    timeout_seconds: int
    max_file_size_bytes: int
    keep_converted_files: bool
    temp_dir: Optional[str]

    def __init__(self, *, env_files: Optional[Sequence[Path]] = None, **data):
        resolved = resolve_hwp_env_settings(env_files)

        data.setdefault("enabled", _parse_bool(resolved.get(_ENV_KEY_ENABLED), True))
        data.setdefault("executable_path", resolved.get(_ENV_KEY_EXECUTABLE))
        data.setdefault(
            "timeout_seconds", _parse_int(resolved.get(_ENV_KEY_TIMEOUT), DEFAULT_TIMEOUT_SECONDS)
        )
        data.setdefault(
            "max_file_size_bytes",
            _parse_int(resolved.get(_ENV_KEY_MAX_SIZE), DEFAULT_MAX_FILE_SIZE_BYTES),
        )
        data.setdefault("keep_converted_files", _parse_bool(resolved.get(_ENV_KEY_KEEP_FILES), False))
        data.setdefault("temp_dir", resolved.get(_ENV_KEY_TEMP_DIR))

        super().__init__(**data)

    def resolve_temp_dir(self) -> Path:
        if self.temp_dir:
            return Path(self.temp_dir)
        return Path(tempfile.gettempdir())


__all__ = [
    "HwpConversionConfig",
    "DEFAULT_TIMEOUT_SECONDS",
    "DEFAULT_MAX_FILE_SIZE_BYTES",
    "resolve_hwp_env_settings",
    "default_env_files",
]
