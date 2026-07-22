# 작성자: 가은/Claude(2026-07-22, 용준 협의 — 동시 변환 실패 대응)
# 목적: convert_to_preview_pdf()의 프로필 전략 검증 — HWP/HWPX는 기본 프로필 +
#       SOFFICE_DEFAULT_PROFILE_LOCK(H2Orestart 확장이 사용자 프로필에만 있어 격리
#       프로필에서는 크래시, 실측 2026-07-22), docx 등 그 외 형식은 기존 격리
#       프로필(-env:UserInstallation, 재인 2026-07-21 실측) 유지.
# import: 표준 라이브러리, pytest; ai.rag.converters 패키지.

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai.rag.converters.config import HwpConversionConfig
from ai.rag.converters.hwp_pdf_converter import SOFFICE_DEFAULT_PROFILE_LOCK
from ai.rag.converters.preview_pdf_converter import convert_to_preview_pdf

_PDF_HEADER = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n" + b"0" * 64


def _config() -> HwpConversionConfig:
    return HwpConversionConfig(
        enabled=True,
        executable_path=None,
        timeout_seconds=30,
        max_file_size_bytes=50 * 1024 * 1024,
        keep_converted_files=False,
    )


@pytest.fixture(autouse=True)
def _fake_executable(monkeypatch):
    monkeypatch.setattr(
        "ai.rag.converters.preview_pdf_converter.find_executable", lambda _path: "/usr/bin/soffice"
    )


def _success_run(command, **kwargs):
    outdir = Path(command[command.index("--outdir") + 1])
    source = Path(command[-1])
    (outdir / f"{source.stem}.pdf").write_bytes(_PDF_HEADER)
    return subprocess.CompletedProcess(command, returncode=0, stdout="", stderr="")


def _convert_and_capture(tmp_path: Path, filename: str) -> tuple[list, Path]:
    source = tmp_path / filename
    source.write_bytes(b"fake-document-bytes")
    out_dir = tmp_path / "out"
    captured = {}

    def _capture(command, **kwargs):
        captured["command"] = command
        captured["lock_free"] = SOFFICE_DEFAULT_PROFILE_LOCK.acquire(blocking=False)
        if captured["lock_free"]:
            SOFFICE_DEFAULT_PROFILE_LOCK.release()
        return _success_run(command, **kwargs)

    with patch("ai.rag.converters.preview_pdf_converter.subprocess.run", side_effect=_capture):
        convert_to_preview_pdf(source, output_dir=out_dir, config=_config())

    return captured, out_dir


class TestProfileStrategy:
    def test_hwp_uses_default_profile_and_holds_lock(self, tmp_path):
        captured, out_dir = _convert_and_capture(tmp_path, "form.hwp")
        env_args = [p for p in captured["command"] if p.startswith("-env:")]
        assert env_args == [], "HWP 미리보기는 기본 프로필을 써야 한다(H2Orestart가 격리 프로필에 없음)"
        assert captured["lock_free"] is False, "HWP 변환 중에는 기본 프로필 락이 잡혀 있어야 한다"
        assert list(out_dir.glob("*_profile")) == []

    def test_hwpx_uses_default_profile_and_holds_lock(self, tmp_path):
        captured, _ = _convert_and_capture(tmp_path, "form.hwpx")
        assert [p for p in captured["command"] if p.startswith("-env:")] == []
        assert captured["lock_free"] is False

    def test_docx_keeps_isolated_profile_without_lock(self, tmp_path):
        captured, out_dir = _convert_and_capture(tmp_path, "plan.docx")
        env_args = [p for p in captured["command"] if p.startswith("-env:UserInstallation=file:")]
        assert len(env_args) == 1, "docx 미리보기는 기존 격리 프로필 방식을 유지해야 한다(재인 실측)"
        assert captured["lock_free"] is True, "격리 프로필 변환은 기본 프로필 락을 잡지 않아야 한다(병렬 유지)"
        # 성공 후 임시 프로필은 정리된다.
        assert list(out_dir.glob("*_profile")) == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
