"""
Unit Tests for ai.rag.converters.config (HWP 환경설정 격리/우선순위)
========================================================================
import-time load_dotenv() 전역 호출을 제거하고, HWP_* 6개 키만 골라
OS 환경변수 > backend/.env > 레포 루트 .env > 코드 기본값 순으로 병합하는
resolve_hwp_env_settings()/HwpConversionConfig를 검증한다.
"""

import importlib
import os

import pytest

import ai.rag.converters.config as config_module
from ai.rag.converters.config import (
    DEFAULT_MAX_FILE_SIZE_BYTES,
    DEFAULT_TIMEOUT_SECONDS,
    HwpConversionConfig,
    resolve_hwp_env_settings,
)

_HWP_ENV_KEYS = (
    "HWP_CONVERSION_ENABLED",
    "HWP_CONVERTER_EXECUTABLE",
    "HWP_CONVERSION_TIMEOUT_SECONDS",
    "HWP_CONVERSION_MAX_FILE_SIZE_BYTES",
    "HWP_CONVERSION_KEEP_FILES",
    "HWP_CONVERSION_TEMP_DIR",
)

# backend/.env가 실제로 읽는 것 중 HWP와 무관한, "새어나가면 안 되는" 키들
_NON_HWP_ENV_KEYS = ("MONGODB_URL", "MONGODB_DB", "OPENAI_API_KEY", "LLM_PROFILE")


@pytest.fixture(autouse=True)
def _clean_hwp_env(monkeypatch):
    """모든 테스트가 실제 OS 환경변수(예: 이 머신에 설정된 HWP_*)의 영향을 받지 않게
    한다 — 테스트는 각자 필요한 값만 명시적으로 setenv한다."""
    for key in _HWP_ENV_KEYS + _NON_HWP_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _write_env_file(path, content: str):
    path.write_text(content, encoding="utf-8")
    return path


class TestImportDoesNotMutateEnviron:
    def test_reimport_does_not_change_os_environ(self, tmp_path, monkeypatch):
        """config 모듈을 (다시) import하는 것만으로 os.environ이 바뀌면 안 된다 —
        과거의 import-time load_dotenv() 전역 호출 회귀를 막는다."""
        backend_env = _write_env_file(
            tmp_path / "backend.env",
            "HWP_CONVERTER_EXECUTABLE=/should/not/leak/into/os/environ\n"
            "MONGODB_URL=mongodb://should-not-leak\n",
        )
        monkeypatch.chdir(tmp_path)

        before = dict(os.environ)
        importlib.reload(config_module)
        after = dict(os.environ)

        assert before == after
        assert "HWP_CONVERTER_EXECUTABLE" not in os.environ
        assert "MONGODB_URL" not in os.environ
        # teardown: 다음 테스트에 영향 주지 않도록 원상태로 다시 reload
        importlib.reload(config_module)

    def test_constructing_config_does_not_mutate_os_environ(self, tmp_path):
        backend_env = _write_env_file(
            tmp_path / "backend.env", "HWP_CONVERTER_EXECUTABLE=/tmp/fake-soffice\n"
        )
        before = dict(os.environ)
        HwpConversionConfig(env_files=(backend_env,))
        assert dict(os.environ) == before


class TestNonHwpKeysNeverLeakOrLoad:
    def test_non_hwp_keys_in_dotenv_are_ignored(self, tmp_path):
        backend_env = _write_env_file(
            tmp_path / "backend.env",
            "HWP_CONVERSION_ENABLED=true\n"
            "MONGODB_URL=mongodb://leaked\n"
            "OPENAI_API_KEY=sk-should-not-be-read\n",
        )
        resolved = resolve_hwp_env_settings(env_files=(backend_env,))
        assert set(resolved.keys()) <= set(_HWP_ENV_KEYS)
        assert "MONGODB_URL" not in resolved
        assert "OPENAI_API_KEY" not in resolved

    def test_config_construction_does_not_read_non_hwp_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-real-secret")
        cfg = HwpConversionConfig(env_files=(tmp_path / "does_not_exist.env",))
        assert not hasattr(cfg, "OPENAI_API_KEY")
        assert "openai" not in cfg.model_dump().__str__().lower()


class TestPrecedence:
    def test_os_env_overrides_backend_env(self, tmp_path, monkeypatch):
        backend_env = _write_env_file(
            tmp_path / "backend.env", "HWP_CONVERTER_EXECUTABLE=/from/backend/env\n"
        )
        monkeypatch.setenv("HWP_CONVERTER_EXECUTABLE", "/from/os/environ")

        resolved = resolve_hwp_env_settings(env_files=(backend_env,))
        assert resolved["HWP_CONVERTER_EXECUTABLE"] == "/from/os/environ"

        cfg = HwpConversionConfig(env_files=(backend_env,))
        assert cfg.executable_path == "/from/os/environ"

    def test_backend_env_overrides_root_env(self, tmp_path):
        backend_env = _write_env_file(
            tmp_path / "backend.env", "HWP_CONVERTER_EXECUTABLE=/from/backend/env\n"
        )
        root_env = _write_env_file(tmp_path / "root.env", "HWP_CONVERTER_EXECUTABLE=/from/root/env\n")

        resolved = resolve_hwp_env_settings(env_files=(backend_env, root_env))
        assert resolved["HWP_CONVERTER_EXECUTABLE"] == "/from/backend/env"

        cfg = HwpConversionConfig(env_files=(backend_env, root_env))
        assert cfg.executable_path == "/from/backend/env"

    def test_root_env_overrides_code_default(self, tmp_path):
        root_env = _write_env_file(tmp_path / "root.env", "HWP_CONVERSION_TIMEOUT_SECONDS=123\n")
        # backend/.env가 없는 상태에서 root .env만 있는 경우
        missing_backend_env = tmp_path / "no_backend.env"

        cfg = HwpConversionConfig(env_files=(missing_backend_env, root_env))
        assert cfg.timeout_seconds == 123

    def test_no_env_files_falls_back_to_code_default(self, tmp_path):
        cfg = HwpConversionConfig(
            env_files=(tmp_path / "missing_backend.env", tmp_path / "missing_root.env")
        )
        assert cfg.enabled is True
        assert cfg.executable_path is None
        assert cfg.timeout_seconds == DEFAULT_TIMEOUT_SECONDS
        assert cfg.max_file_size_bytes == DEFAULT_MAX_FILE_SIZE_BYTES
        assert cfg.keep_converted_files is False
        assert cfg.temp_dir is None


class TestEmptyStringHandling:
    def test_empty_string_in_os_environ_treated_as_unset(self, tmp_path, monkeypatch):
        backend_env = _write_env_file(
            tmp_path / "backend.env", "HWP_CONVERTER_EXECUTABLE=/from/backend/env\n"
        )
        monkeypatch.setenv("HWP_CONVERTER_EXECUTABLE", "")

        resolved = resolve_hwp_env_settings(env_files=(backend_env,))
        assert resolved["HWP_CONVERTER_EXECUTABLE"] == "/from/backend/env"

    def test_empty_string_in_dotenv_file_treated_as_unset(self, tmp_path):
        backend_env = _write_env_file(
            tmp_path / "backend.env",
            "HWP_CONVERTER_EXECUTABLE=\n"  # 빈 값 (예: .env.example 스타일)
            "HWP_CONVERSION_TEMP_DIR=\n",
        )
        cfg = HwpConversionConfig(env_files=(backend_env,))
        assert cfg.executable_path is None
        assert cfg.temp_dir is None


class TestInvalidIntFallback:
    def test_invalid_timeout_falls_back_to_default(self, tmp_path):
        backend_env = _write_env_file(
            tmp_path / "backend.env", "HWP_CONVERSION_TIMEOUT_SECONDS=not-a-number\n"
        )
        cfg = HwpConversionConfig(env_files=(backend_env,))
        assert cfg.timeout_seconds == DEFAULT_TIMEOUT_SECONDS


class TestMissingDotenvFiles:
    def test_missing_backend_and_root_env_does_not_raise(self, tmp_path):
        cfg = HwpConversionConfig(
            env_files=(tmp_path / "no_backend.env", tmp_path / "no_root.env")
        )
        assert cfg.enabled is True


class TestExistingCallCompat:
    def test_no_arg_construction_still_works(self):
        """기존 HwpConversionConfig() 호출부(factory.py, hwp_pdf_converter.py)와의 호환성."""
        cfg = HwpConversionConfig()
        assert isinstance(cfg.enabled, bool)
        assert isinstance(cfg.timeout_seconds, int)

    def test_explicit_kwargs_still_override_env(self, tmp_path):
        backend_env = _write_env_file(
            tmp_path / "backend.env", "HWP_CONVERSION_ENABLED=true\n"
        )
        cfg = HwpConversionConfig(enabled=False, executable_path=None, env_files=(backend_env,))
        assert cfg.enabled is False

    def test_resolve_temp_dir_unchanged(self, tmp_path):
        cfg = HwpConversionConfig(
            temp_dir=str(tmp_path), env_files=(tmp_path / "missing.env",)
        )
        assert cfg.resolve_temp_dir() == tmp_path
