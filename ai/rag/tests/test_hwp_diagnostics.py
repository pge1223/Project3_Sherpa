"""
Unit Tests for ai.rag.converters.diagnostics
==================================================
LibreOffice/Java/H2Orestart가 실제로 설치되어 있지 않은 환경에서도 실행 가능하도록
모든 subprocess 호출과 실행 파일 탐색을 mock한다.

LibreOffice의 "정상 동작" 여부는 `soffice --version`이 아니라 실제 `--convert-to pdf`
자기 진단(self-test)으로 확인한다 — 실제 Windows 설치본에서 `--version`/`--help`은
안정적으로 hang되지만 `--convert-to pdf`는 항상 빠르게 성공하는 것이 확인됐다
(ai/rag/converters/diagnostics.py의 _check_soffice_can_convert 문서 참고). 그래서 아래
mock들은 "--outdir 뒤에 지정된 폴더에 {소스파일명}.pdf를 만들어주는" 가짜 subprocess.run을
쓴다 — test_hwp_pdf_converter.py의 _success_run_factory와 같은 패턴.
"""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from ai.rag.converters.config import HwpConversionConfig
from ai.rag.converters.diagnostics import (
    HwpDiagnosticsResult,
    _is_h2orestart_registered,
    log_hwp_diagnostics,
    run_hwp_diagnostics,
)

_PDF_HEADER = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n" + b"0" * 64


def _config(tmp_path, **overrides) -> HwpConversionConfig:
    base = {
        "enabled": True,
        "executable_path": None,
        "temp_dir": str(tmp_path),
        "env_files": (tmp_path / "missing.env",),
    }
    base.update(overrides)
    return HwpConversionConfig(**base)


def _fake_soffice(tmp_path, unopkg_name: str = "unopkg") -> str:
    """soffice + 같은 디렉터리에 unopkg가 있는 가짜 LibreOffice 설치를 만든다."""
    program_dir = tmp_path / "program"
    program_dir.mkdir(parents=True, exist_ok=True)
    soffice = program_dir / "soffice"
    soffice.write_text("")
    (program_dir / unopkg_name).write_text("")
    return str(soffice)


def _successful_convert(command: list[str]) -> subprocess.CompletedProcess:
    """--convert-to pdf 호출을 흉내내 --outdir 위치에 진짜 PDF 매직넘버가 담긴 파일을 만든다."""
    outdir = Path(command[command.index("--outdir") + 1])
    source = Path(command[-1])
    (outdir / f"{source.stem}.pdf").write_bytes(_PDF_HEADER)
    return subprocess.CompletedProcess(command, returncode=0, stdout="", stderr="")


_H2ORESTART_REGISTERED_OUTPUT = "Identifier: ebandal.libreoffice.H2Orestart\n  Version: 0.7.13\n  is registered: yes\n"


def _dispatch(command: list[str], *, convert_ok=True, unopkg_stdout=_H2ORESTART_REGISTERED_OUTPUT, **_kwargs):
    """soffice convert-probe / unopkg list / java -version 세 종류를 명령어 모양으로 구분."""
    if "--convert-to" in command:
        if not convert_ok:
            return subprocess.CompletedProcess(command, returncode=1, stdout="", stderr="boom")
        return _successful_convert(command)
    if "list" in command:
        return subprocess.CompletedProcess(command, returncode=0, stdout=unopkg_stdout, stderr="")
    return subprocess.CompletedProcess(command, returncode=0, stdout="", stderr="")


class TestDisabled:
    def test_disabled_short_circuits_everything(self, tmp_path):
        config = _config(tmp_path, enabled=False)
        result = run_hwp_diagnostics(config)
        assert result == HwpDiagnosticsResult(
            enabled=False,
            available=False,
            libreoffice=False,
            h2orestart=False,
            java=False,
            temp_dir_writable=False,
            reason="HWP conversion is disabled",
        )


class TestFullySuccessful:
    def test_all_checks_pass(self, tmp_path):
        soffice_path = _fake_soffice(tmp_path)
        config = _config(tmp_path, executable_path=soffice_path)

        with patch("ai.rag.converters.diagnostics.shutil.which", return_value="/usr/bin/java"), patch(
            "ai.rag.converters.diagnostics.subprocess.run", side_effect=_dispatch
        ):
            result = run_hwp_diagnostics(config)

        assert result.enabled is True
        assert result.available is True
        assert result.libreoffice is True
        assert result.java is True
        assert result.h2orestart is True
        assert result.temp_dir_writable is True
        assert result.reason is None


class TestSofficeNotFound:
    def test_soffice_missing_marks_unavailable(self, tmp_path):
        config = _config(tmp_path, executable_path=None)
        with patch("ai.rag.converters.diagnostics.find_executable", return_value=None), patch(
            "ai.rag.converters.diagnostics.shutil.which", return_value="/usr/bin/java"
        ), patch("ai.rag.converters.diagnostics.subprocess.run", side_effect=_dispatch):
            result = run_hwp_diagnostics(config)

        assert result.available is False
        assert result.libreoffice is False
        assert result.h2orestart is False
        assert result.reason == "LibreOffice(soffice) executable was not found"


class TestSofficeConvertProbeFails:
    def test_convert_probe_returns_nonzero(self, tmp_path):
        soffice_path = _fake_soffice(tmp_path)
        config = _config(tmp_path, executable_path=soffice_path)

        def _fake_run(command, **kwargs):
            return _dispatch(command, convert_ok=False)

        with patch("ai.rag.converters.diagnostics.shutil.which", return_value="/usr/bin/java"), patch(
            "ai.rag.converters.diagnostics.subprocess.run", side_effect=_fake_run
        ):
            result = run_hwp_diagnostics(config)

        assert result.libreoffice is False
        assert result.available is False
        assert result.reason == "LibreOffice(soffice) failed a minimal headless conversion self-test"

    def test_convert_probe_times_out(self, tmp_path):
        soffice_path = _fake_soffice(tmp_path)
        config = _config(tmp_path, executable_path=soffice_path)

        def _fake_run(command, **kwargs):
            if "--convert-to" in command:
                raise subprocess.TimeoutExpired(cmd=command, timeout=25)
            return _dispatch(command)

        with patch("ai.rag.converters.diagnostics.shutil.which", return_value="/usr/bin/java"), patch(
            "ai.rag.converters.diagnostics.subprocess.run", side_effect=_fake_run
        ):
            result = run_hwp_diagnostics(config)

        assert result.libreoffice is False
        assert result.available is False
        assert result.reason == "LibreOffice(soffice) failed a minimal headless conversion self-test"

    def test_convert_probe_leaves_no_leftover_files(self, tmp_path):
        """진단용 probe 파일(txt/pdf)이 성공/실패 어느 경우든 정리되는지 확인한다."""
        soffice_path = _fake_soffice(tmp_path)
        config = _config(tmp_path, executable_path=soffice_path)

        with patch("ai.rag.converters.diagnostics.shutil.which", return_value="/usr/bin/java"), patch(
            "ai.rag.converters.diagnostics.subprocess.run", side_effect=_dispatch
        ):
            run_hwp_diagnostics(config)

        probe_dir = tmp_path / "hwp_conversion" / "_diagnostics_probe"
        assert not probe_dir.exists() or list(probe_dir.iterdir()) == []


class TestJavaNotFound:
    def test_java_missing(self, tmp_path):
        soffice_path = _fake_soffice(tmp_path)
        config = _config(tmp_path, executable_path=soffice_path)

        with patch("ai.rag.converters.diagnostics.shutil.which", return_value=None), patch(
            "ai.rag.converters.diagnostics.subprocess.run", side_effect=_dispatch
        ):
            result = run_hwp_diagnostics(config)

        assert result.java is False
        assert result.available is False
        assert result.reason == "Java runtime was not found"


class TestH2OrestartParsing:
    """_is_h2orestart_registered()를 unopkg list 출력 텍스트만 가지고 직접 검증한다
    (subprocess/파일시스템 없이 순수 텍스트 파싱만 테스트)."""

    def test_h2orestart_registered_yes_passes(self):
        output = (
            "Identifier: ebandal.libreoffice.H2Orestart\n"
            "  Version: 0.7.13\n"
            "  is registered: yes\n"
            "  bundled Packages: {\n"
            "      is registered: yes\n"
            "  }\n"
        )
        assert _is_h2orestart_registered(output) is True

    def test_h2orestart_registered_no_fails(self):
        output = "Identifier: ebandal.libreoffice.H2Orestart\n  Version: 0.7.13\n  is registered: no\n"
        assert _is_h2orestart_registered(output) is False

    def test_h2orestart_name_only_no_registered_line_fails(self):
        """식별자 블록 안에 등록 상태 줄이 아예 없으면(다음 확장의 상태를 빌려오면 안 됨)
        미등록으로 취급해야 한다."""
        output = (
            "Identifier: ebandal.libreoffice.H2Orestart\n"
            "  Version: 0.7.13\n"
            "\n"
            "Identifier: some.other.extension\n"
            "  is registered: yes\n"
        )
        assert _is_h2orestart_registered(output) is False

    def test_other_extension_registered_h2orestart_not_fails(self):
        output = (
            "Identifier: some.other.extension\n"
            "  is registered: yes\n"
            "\n"
            "Identifier: ebandal.libreoffice.H2Orestart\n"
            "  is registered: no\n"
        )
        assert _is_h2orestart_registered(output) is False

    def test_h2orestart_registered_among_multiple_extensions_passes(self):
        output = (
            "Identifier: some.other.extension\n"
            "  is registered: no\n"
            "\n"
            "Identifier: ebandal.libreoffice.H2Orestart\n"
            "  is registered: yes\n"
            "\n"
            "Identifier: another.extension\n"
            "  is registered: yes\n"
        )
        assert _is_h2orestart_registered(output) is True

    def test_case_and_whitespace_and_crlf_are_tolerated(self):
        output = (
            "IDENTIFIER:   EBANDAL.LIBREOFFICE.H2ORESTART  \r\n"
            "  Version: 0.7.13\r\n"
            "  Is Registered:   YES   \r\n"
        )
        assert _is_h2orestart_registered(output) is True

    def test_no_h2orestart_identifier_at_all_fails(self):
        output = "Identifier: some.other.extension\n  is registered: yes\n"
        assert _is_h2orestart_registered(output) is False

    def test_empty_output_fails(self):
        assert _is_h2orestart_registered("") is False


class TestH2OrestartNotRegistered:
    def test_unopkg_list_missing_h2orestart(self, tmp_path):
        soffice_path = _fake_soffice(tmp_path)
        config = _config(tmp_path, executable_path=soffice_path)

        def _fake_run(command, **kwargs):
            return _dispatch(command, unopkg_stdout="Identifier: some.other.extension\n  is registered: yes\n")

        with patch("ai.rag.converters.diagnostics.shutil.which", return_value="/usr/bin/java"), patch(
            "ai.rag.converters.diagnostics.subprocess.run", side_effect=_fake_run
        ):
            result = run_hwp_diagnostics(config)

        assert result.h2orestart is False
        assert result.available is False
        assert result.reason == "H2Orestart extension is not registered for the backend runtime user"

    def test_unopkg_list_h2orestart_present_but_deregistered(self, tmp_path):
        """H2Orestart 문자열이 출력에 있어도 "is registered: no"면 실패해야 한다 —
        예전 방식(문자열만 확인)이 놓치던 케이스."""
        soffice_path = _fake_soffice(tmp_path)
        config = _config(tmp_path, executable_path=soffice_path)

        def _fake_run(command, **kwargs):
            return _dispatch(
                command,
                unopkg_stdout="Identifier: ebandal.libreoffice.H2Orestart\n  is registered: no\n",
            )

        with patch("ai.rag.converters.diagnostics.shutil.which", return_value="/usr/bin/java"), patch(
            "ai.rag.converters.diagnostics.subprocess.run", side_effect=_fake_run
        ):
            result = run_hwp_diagnostics(config)

        assert result.h2orestart is False
        assert result.available is False
        assert result.reason == "H2Orestart extension is not registered for the backend runtime user"


class TestUnopkgExecutionFails:
    def test_unopkg_not_found_next_to_soffice(self, tmp_path):
        program_dir = tmp_path / "program"
        program_dir.mkdir(parents=True, exist_ok=True)
        soffice_path = program_dir / "soffice"
        soffice_path.write_text("")  # unopkg 없음
        config = _config(tmp_path, executable_path=str(soffice_path))

        with patch("ai.rag.converters.diagnostics.shutil.which", return_value="/usr/bin/java"), patch(
            "ai.rag.converters.diagnostics.subprocess.run", side_effect=_dispatch
        ):
            result = run_hwp_diagnostics(config)

        assert result.h2orestart is False
        assert result.reason == "unopkg executable was not found next to LibreOffice"

    def test_unopkg_raises_oserror(self, tmp_path):
        soffice_path = _fake_soffice(tmp_path)
        config = _config(tmp_path, executable_path=soffice_path)

        def _fake_run(command, **kwargs):
            if "list" in command:
                raise OSError("permission denied")
            return _dispatch(command)

        with patch("ai.rag.converters.diagnostics.shutil.which", return_value="/usr/bin/java"), patch(
            "ai.rag.converters.diagnostics.subprocess.run", side_effect=_fake_run
        ):
            result = run_hwp_diagnostics(config)

        assert result.h2orestart is False
        assert result.reason == "unopkg list failed to run (see server logs for details)"


class TestTempDirNotWritable:
    def test_temp_dir_write_failure(self, tmp_path):
        soffice_path = _fake_soffice(tmp_path)
        config = _config(tmp_path, executable_path=soffice_path)

        with patch("ai.rag.converters.diagnostics.shutil.which", return_value="/usr/bin/java"), patch(
            "ai.rag.converters.diagnostics.subprocess.run", side_effect=_dispatch
        ), patch("ai.rag.converters.diagnostics._check_temp_dir_writable", return_value=False):
            result = run_hwp_diagnostics(config)

        assert result.temp_dir_writable is False
        assert result.available is False
        assert result.reason == "HWP conversion temp directory is not writable"


class TestDiagnosticsNeverRaises:
    def test_unexpected_exception_after_enabled_known_preserves_enabled_true(self, tmp_path):
        """config.enabled=True를 이미 확인한 뒤(즉 활성화 상태였다는 게 확실한 뒤)
        예외가 나면, enabled=False(=의도적 비활성화)로 위장하지 않고 enabled=True를
        보존해야 /health가 "degraded"로 실제 장애를 드러낸다."""
        config = _config(tmp_path)
        assert config.enabled is True
        with patch("ai.rag.converters.diagnostics.find_executable", side_effect=RuntimeError("boom")):
            result = run_hwp_diagnostics(config)

        assert result.enabled is True
        assert result.available is False
        assert result.reason == "HWP diagnostics failed unexpectedly (see server logs)"
        # 원본 예외 메시지("boom")나 절대 경로가 새어나가면 안 된다.
        assert "boom" not in (result.reason or "")

    def test_exception_before_enabled_known_fails_safe_to_enabled_true(self, tmp_path):
        """HwpConversionConfig() 생성 자체가 실패하면 활성화 여부조차 알 수 없다 —
        이런 "알 수 없음"을 enabled=False(정상적인 의도적 비활성화)로 위장하지 않고
        enabled=True로 fail-safe 처리해 /health가 degraded가 되게 한다."""
        with patch(
            "ai.rag.converters.diagnostics.HwpConversionConfig", side_effect=RuntimeError("config boom")
        ):
            result = run_hwp_diagnostics(None)

        assert result.enabled is True
        assert result.available is False
        assert result.reason == "HWP diagnostics failed unexpectedly (see server logs)"
        assert "config boom" not in (result.reason or "")

    def test_disabled_short_circuit_is_not_affected_by_failsafe(self, tmp_path):
        """enabled=false로 명시적으로 끈 정상 경로는 fail-safe 정책과 무관하게
        그대로 enabled=False를 유지해야 한다(=/health status="ok")."""
        config = _config(tmp_path, enabled=False)
        result = run_hwp_diagnostics(config)
        assert result.enabled is False
        assert result.reason == "HWP conversion is disabled"


class TestLogging:
    def test_log_ready_does_not_raise(self):
        result = HwpDiagnosticsResult(
            enabled=True,
            available=True,
            libreoffice=True,
            h2orestart=True,
            java=True,
            temp_dir_writable=True,
            reason=None,
        )
        log_hwp_diagnostics(result)  # 예외 없이 끝나면 충분

    def test_log_unavailable_does_not_raise(self):
        result = HwpDiagnosticsResult(
            enabled=True,
            available=False,
            libreoffice=True,
            h2orestart=False,
            java=True,
            temp_dir_writable=True,
            reason="H2Orestart extension is not registered for the backend runtime user",
        )
        log_hwp_diagnostics(result)
