"""
Unit Tests for ai.rag.converters (HWP/HWPX -> PDF)
========================================================
실제 LibreOffice 실행 파일 없이도 실행 가능하도록 subprocess.run과 shutil.which를 mock한다.
"""

import subprocess
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from ai.rag.converters.config import HwpConversionConfig
from ai.rag.converters.exceptions import (
    ConversionProcessError,
    ConversionTimeoutError,
    ConverterUnavailableError,
    ConvertedFileNotFoundError,
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
    HwpPdfConverter,
    find_executable,
    looks_like_hwp,
    looks_like_hwpx,
)
from ai.rag.converters.schemas import ConversionStatus, build_conversion_metadata

_HWP_OLE_HEADER = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 32
_PDF_HEADER = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n" + b"0" * 64


def _write_fake_hwp(path: Path) -> Path:
    path.write_bytes(_HWP_OLE_HEADER)
    return path


def _write_fake_hwpx(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("Contents/content.hpf", "<xml/>")
    return path


def _config(**overrides) -> HwpConversionConfig:
    # executable_path는 명시적으로 넘기지 않는 한 None으로 둔다 — find_executable()이
    # PATH 탐색(shutil.which) 경로를 타게 해서, 아래 autouse fixture가 patch한 가짜
    # soffice 경로를 쓰도록 한다. 실제 파일시스템에 존재하지 않는 경로를 하드코딩하면
    # 이 환경(LibreOffice 미설치)에서 항상 ConverterUnavailableError가 난다.
    base = {
        "enabled": True,
        "executable_path": None,
        "timeout_seconds": 30,
        "max_file_size_bytes": 50 * 1024 * 1024,
        "keep_converted_files": False,
    }
    base.update(overrides)
    return HwpConversionConfig(**base)


@pytest.fixture(autouse=True)
def _default_executable_lookup(monkeypatch):
    """LibreOffice가 설치되지 않은 환경에서도 변환 로직을 검증할 수 있도록 PATH 탐색
    결과를 가짜 경로로 고정한다. 개별 테스트가 shutil.which를 직접 patch하면 그쪽이
    우선한다(중첩 patch)."""
    monkeypatch.setattr(
        "ai.rag.converters.hwp_pdf_converter.shutil.which", lambda name: "/usr/bin/soffice"
    )


def _success_run_factory(pdf_header: bytes = _PDF_HEADER):
    """--outdir/변환 대상 인자를 파싱해 해당 위치에 가짜 PDF를 생성하는 subprocess.run 대체 함수."""

    def _fake_run(command, **kwargs):
        outdir = Path(command[command.index("--outdir") + 1])
        source = Path(command[-1])
        (outdir / f"{source.stem}.pdf").write_bytes(pdf_header)
        return subprocess.CompletedProcess(command, returncode=0, stdout="", stderr="")

    return _fake_run


class TestSupports:
    def test_hwp_supported(self, tmp_path):
        converter = HwpPdfConverter(config=_config())
        assert converter.supports(tmp_path / "a.hwp") is True

    def test_hwpx_supported(self, tmp_path):
        converter = HwpPdfConverter(config=_config())
        assert converter.supports(tmp_path / "a.hwpx") is True

    def test_uppercase_extension_supported(self, tmp_path):
        converter = HwpPdfConverter(config=_config())
        assert converter.supports(tmp_path / "a.HWP") is True
        assert converter.supports(tmp_path / "a.HWPX") is True

    def test_pdf_docx_pptx_not_supported(self, tmp_path):
        converter = HwpPdfConverter(config=_config())
        assert converter.supports(tmp_path / "a.pdf") is False
        assert converter.supports(tmp_path / "a.docx") is False
        assert converter.supports(tmp_path / "a.pptx") is False


class TestSignatureValidation:
    def test_looks_like_hwp_true_for_ole_header(self, tmp_path):
        path = _write_fake_hwp(tmp_path / "a.hwp")
        assert looks_like_hwp(path) is True

    def test_looks_like_hwp_false_for_random_bytes(self, tmp_path):
        path = tmp_path / "a.hwp"
        path.write_bytes(b"not an ole file")
        assert looks_like_hwp(path) is False

    def test_looks_like_hwpx_true_for_valid_zip(self, tmp_path):
        path = _write_fake_hwpx(tmp_path / "a.hwpx")
        assert looks_like_hwpx(path) is True

    def test_looks_like_hwpx_false_for_non_zip(self, tmp_path):
        path = tmp_path / "a.hwpx"
        path.write_bytes(b"not a zip file")
        assert looks_like_hwpx(path) is False

    def test_convert_rejects_hwp_with_wrong_signature(self, tmp_path):
        source = tmp_path / "fake.hwp"
        source.write_bytes(b"PK\x03\x04this is actually a zip")
        converter = HwpPdfConverter(config=_config())
        with pytest.raises(InvalidSourceFileError):
            converter.convert(source)

    def test_convert_rejects_hwpx_with_wrong_signature(self, tmp_path):
        source = tmp_path / "fake.hwpx"
        source.write_bytes(_HWP_OLE_HEADER)
        converter = HwpPdfConverter(config=_config())
        with pytest.raises(InvalidSourceFileError):
            converter.convert(source)


class TestFindExecutable:
    def test_explicit_path_used_if_exists(self, tmp_path):
        fake_exe = tmp_path / "soffice"
        fake_exe.write_text("")
        assert find_executable(str(fake_exe)) == str(fake_exe)

    def test_explicit_path_missing_returns_none(self, tmp_path):
        assert find_executable(str(tmp_path / "does_not_exist")) is None

    def test_path_lookup_when_not_configured(self):
        with patch("ai.rag.converters.hwp_pdf_converter.shutil.which", return_value="/usr/bin/soffice"):
            assert find_executable(None) == "/usr/bin/soffice"

    def test_none_when_nothing_found(self):
        with patch("ai.rag.converters.hwp_pdf_converter.shutil.which", return_value=None), patch(
            "ai.rag.converters.hwp_pdf_converter._WINDOWS_DEFAULT_INSTALL_PATHS", ()
        ):
            assert find_executable(None) is None

    def test_windows_default_install_path_used_as_last_resort(self, tmp_path):
        """PATH에 없어도 흔한 Windows 기본 설치 경로에 실제 파일이 있으면 그걸 찾아야 한다
        (winget/공식 인스톨러는 기본적으로 PATH에 soffice를 추가하지 않는다)."""
        fake_default_install = tmp_path / "soffice.exe"
        fake_default_install.write_text("")
        with patch("ai.rag.converters.hwp_pdf_converter.shutil.which", return_value=None), patch(
            "ai.rag.converters.hwp_pdf_converter._WINDOWS_DEFAULT_INSTALL_PATHS",
            (str(fake_default_install),),
        ):
            assert find_executable(None) == str(fake_default_install)

    def test_windows_default_install_path_skipped_when_missing(self, tmp_path):
        with patch("ai.rag.converters.hwp_pdf_converter.shutil.which", return_value=None), patch(
            "ai.rag.converters.hwp_pdf_converter._WINDOWS_DEFAULT_INSTALL_PATHS",
            (str(tmp_path / "does_not_exist.exe"),),
        ):
            assert find_executable(None) is None


class TestConvertValidation:
    def test_unsupported_extension_raises(self, tmp_path):
        source = tmp_path / "a.pdf"
        source.write_bytes(b"%PDF-1.4")
        converter = HwpPdfConverter(config=_config())
        with pytest.raises(UnsupportedConversionFormatError):
            converter.convert(source)

    def test_disabled_config_raises_unavailable(self, tmp_path):
        source = _write_fake_hwp(tmp_path / "a.hwp")
        converter = HwpPdfConverter(config=_config(enabled=False))
        with pytest.raises(ConverterUnavailableError):
            converter.convert(source)

    def test_missing_source_raises(self, tmp_path):
        converter = HwpPdfConverter(config=_config())
        with pytest.raises(InvalidSourceFileError):
            converter.convert(tmp_path / "missing.hwp")

    def test_empty_source_raises(self, tmp_path):
        source = tmp_path / "empty.hwp"
        source.write_bytes(b"")
        converter = HwpPdfConverter(config=_config())
        with pytest.raises(InvalidSourceFileError):
            converter.convert(source)

    def test_oversized_source_raises(self, tmp_path):
        source = _write_fake_hwp(tmp_path / "big.hwp")
        converter = HwpPdfConverter(config=_config(max_file_size_bytes=4))
        with pytest.raises(SourceFileTooLargeError):
            converter.convert(source)

    def test_executable_not_found_raises_unavailable(self, tmp_path):
        source = _write_fake_hwp(tmp_path / "a.hwp")
        converter = HwpPdfConverter(config=_config(executable_path=None))
        with patch("ai.rag.converters.hwp_pdf_converter.shutil.which", return_value=None), patch(
            "ai.rag.converters.hwp_pdf_converter._WINDOWS_DEFAULT_INSTALL_PATHS", ()
        ):
            with pytest.raises(ConverterUnavailableError):
                converter.convert(source)


class TestConvertSuccess:
    def test_successful_conversion_returns_result(self, tmp_path):
        source = _write_fake_hwp(tmp_path / "사업계획서.hwp")
        output_dir = tmp_path / "work"
        converter = HwpPdfConverter(config=_config())

        with patch("ai.rag.converters.hwp_pdf_converter.subprocess.run", side_effect=_success_run_factory()):
            result = converter.convert(source, output_dir=output_dir)

        assert result.success is True
        assert result.original_file_type == "hwp"
        assert result.converted_file_type == "pdf"
        assert result.converter_name == "libreoffice-headless"
        assert Path(result.converted_path).exists()
        assert Path(result.converted_path).suffix == ".pdf"
        assert result.duration_ms is not None

    def test_command_uses_argument_list_not_shell(self, tmp_path):
        source = _write_fake_hwp(tmp_path / "a.hwp")
        converter = HwpPdfConverter(config=_config())
        captured = {}

        def _capture_and_succeed(command, **kwargs):
            captured["command"] = command
            captured["kwargs"] = kwargs
            return _success_run_factory()(command, **kwargs)

        with patch("ai.rag.converters.hwp_pdf_converter.subprocess.run", side_effect=_capture_and_succeed):
            converter.convert(source, output_dir=tmp_path / "work")

        assert isinstance(captured["command"], list)
        assert captured["kwargs"].get("shell", False) is False
        assert "--headless" in captured["command"]
        assert "--outdir" in captured["command"]

    def test_timeout_passed_to_subprocess(self, tmp_path):
        source = _write_fake_hwp(tmp_path / "a.hwp")
        converter = HwpPdfConverter(config=_config(timeout_seconds=42))
        captured = {}

        def _capture_and_succeed(command, **kwargs):
            captured["timeout"] = kwargs.get("timeout")
            return _success_run_factory()(command, **kwargs)

        with patch("ai.rag.converters.hwp_pdf_converter.subprocess.run", side_effect=_capture_and_succeed):
            converter.convert(source, output_dir=tmp_path / "work")

        assert captured["timeout"] == 42

    def test_original_file_not_modified(self, tmp_path):
        source = _write_fake_hwp(tmp_path / "a.hwp")
        original_bytes = source.read_bytes()
        converter = HwpPdfConverter(config=_config())

        with patch("ai.rag.converters.hwp_pdf_converter.subprocess.run", side_effect=_success_run_factory()):
            converter.convert(source, output_dir=tmp_path / "work")

        assert source.read_bytes() == original_bytes
        assert source.exists()

    def test_output_path_does_not_collide_across_calls(self, tmp_path):
        source = _write_fake_hwp(tmp_path / "a.hwp")
        converter = HwpPdfConverter(config=_config(keep_converted_files=True))
        output_dir = tmp_path / "work"

        with patch("ai.rag.converters.hwp_pdf_converter.subprocess.run", side_effect=_success_run_factory()):
            result1 = converter.convert(source, output_dir=output_dir)
            result2 = converter.convert(source, output_dir=output_dir)

        assert result1.converted_path != result2.converted_path
        assert Path(result1.converted_path).exists()
        assert Path(result2.converted_path).exists()


class TestConvertFailure:
    def test_nonzero_return_code_raises_process_error(self, tmp_path):
        source = _write_fake_hwp(tmp_path / "a.hwp")
        converter = HwpPdfConverter(config=_config())

        def _fail(command, **kwargs):
            return subprocess.CompletedProcess(command, returncode=1, stdout="", stderr="internal libreoffice error")

        with patch("ai.rag.converters.hwp_pdf_converter.subprocess.run", side_effect=_fail):
            with pytest.raises(ConversionProcessError):
                converter.convert(source, output_dir=tmp_path / "work")

    def test_timeout_raises_conversion_timeout_error(self, tmp_path):
        source = _write_fake_hwp(tmp_path / "a.hwp")
        converter = HwpPdfConverter(config=_config())

        def _timeout(command, **kwargs):
            raise subprocess.TimeoutExpired(cmd=command, timeout=kwargs.get("timeout", 30))

        with patch("ai.rag.converters.hwp_pdf_converter.subprocess.run", side_effect=_timeout):
            with pytest.raises(ConversionTimeoutError):
                converter.convert(source, output_dir=tmp_path / "work")

    def test_missing_output_raises_not_found_error(self, tmp_path):
        source = _write_fake_hwp(tmp_path / "a.hwp")
        converter = HwpPdfConverter(config=_config())

        def _no_output(command, **kwargs):
            return subprocess.CompletedProcess(command, returncode=0, stdout="", stderr="")

        with patch("ai.rag.converters.hwp_pdf_converter.subprocess.run", side_effect=_no_output):
            with pytest.raises(ConvertedFileNotFoundError):
                converter.convert(source, output_dir=tmp_path / "work")

    def test_empty_output_raises_invalid_pdf_error(self, tmp_path):
        source = _write_fake_hwp(tmp_path / "a.hwp")
        converter = HwpPdfConverter(config=_config())

        with patch(
            "ai.rag.converters.hwp_pdf_converter.subprocess.run",
            side_effect=_success_run_factory(pdf_header=b""),
        ):
            with pytest.raises(InvalidConvertedPdfError):
                converter.convert(source, output_dir=tmp_path / "work")

    def test_invalid_pdf_header_raises_invalid_pdf_error(self, tmp_path):
        source = _write_fake_hwp(tmp_path / "a.hwp")
        converter = HwpPdfConverter(config=_config())

        with patch(
            "ai.rag.converters.hwp_pdf_converter.subprocess.run",
            side_effect=_success_run_factory(pdf_header=b"not a real pdf file"),
        ):
            with pytest.raises(InvalidConvertedPdfError):
                converter.convert(source, output_dir=tmp_path / "work")

    def test_stderr_not_exposed_in_user_message(self, tmp_path):
        source = _write_fake_hwp(tmp_path / "a.hwp")
        converter = HwpPdfConverter(config=_config())
        sensitive_stderr = "/very/sensitive/internal/server/path/leaked in stderr"

        def _fail(command, **kwargs):
            return subprocess.CompletedProcess(command, returncode=1, stdout="", stderr=sensitive_stderr)

        with patch("ai.rag.converters.hwp_pdf_converter.subprocess.run", side_effect=_fail):
            with pytest.raises(ConversionProcessError) as exc_info:
                converter.convert(source, output_dir=tmp_path / "work")

        assert sensitive_stderr not in exc_info.value.user_message

    def test_all_conversion_errors_have_safe_user_message(self, tmp_path):
        source = tmp_path / "missing.hwp"
        converter = HwpPdfConverter(config=_config())
        with pytest.raises(InvalidSourceFileError) as exc_info:
            converter.convert(source)
        assert str(tmp_path) not in exc_info.value.user_message


class TestFactory:
    def test_requires_conversion_true_for_hwp_hwpx(self, tmp_path):
        assert requires_conversion(tmp_path / "a.hwp") is True
        assert requires_conversion(tmp_path / "a.hwpx") is True

    def test_requires_conversion_false_for_pdf_docx_pptx(self, tmp_path):
        assert requires_conversion(tmp_path / "a.pdf") is False
        assert requires_conversion(tmp_path / "a.docx") is False
        assert requires_conversion(tmp_path / "a.pptx") is False

    def test_get_converter_for_returns_none_for_pdf(self, tmp_path):
        assert get_converter_for(tmp_path / "a.pdf") is None

    def test_get_converter_for_returns_converter_for_hwp(self, tmp_path):
        converter = get_converter_for(tmp_path / "a.hwp", config=_config())
        assert isinstance(converter, HwpPdfConverter)

    def test_convert_if_needed_none_for_pdf(self, tmp_path):
        source = tmp_path / "a.pdf"
        source.write_bytes(b"%PDF-1.4")
        assert convert_if_needed(source) is None

    def test_convert_if_needed_converts_hwp(self, tmp_path):
        source = _write_fake_hwp(tmp_path / "a.hwp")
        with patch("ai.rag.converters.hwp_pdf_converter.subprocess.run", side_effect=_success_run_factory()):
            result = convert_if_needed(source, output_dir=tmp_path / "work", config=_config())
        assert result is not None
        assert result.success is True

    def test_convert_if_needed_propagates_failure(self, tmp_path):
        source = _write_fake_hwp(tmp_path / "a.hwp")

        def _fail(command, **kwargs):
            return subprocess.CompletedProcess(command, returncode=1, stdout="", stderr="boom")

        with patch("ai.rag.converters.hwp_pdf_converter.subprocess.run", side_effect=_fail):
            with pytest.raises(ConversionProcessError):
                convert_if_needed(source, output_dir=tmp_path / "work", config=_config())

    def test_cleanup_deletes_converted_file_by_default(self, tmp_path):
        source = _write_fake_hwp(tmp_path / "a.hwp")
        with patch("ai.rag.converters.hwp_pdf_converter.subprocess.run", side_effect=_success_run_factory()):
            result = convert_if_needed(source, output_dir=tmp_path / "work", config=_config())

        assert Path(result.converted_path).exists()
        cleanup_converted_file(result, config=_config(keep_converted_files=False))
        assert not Path(result.converted_path).exists()
        assert source.exists()

    def test_cleanup_keeps_file_when_configured(self, tmp_path):
        source = _write_fake_hwp(tmp_path / "a.hwp")
        with patch("ai.rag.converters.hwp_pdf_converter.subprocess.run", side_effect=_success_run_factory()):
            result = convert_if_needed(source, output_dir=tmp_path / "work", config=_config(keep_converted_files=True))

        cleanup_converted_file(result, config=_config(keep_converted_files=True))
        assert Path(result.converted_path).exists()

    def test_cleanup_none_result_is_noop(self):
        cleanup_converted_file(None)

    def test_cleanup_failed_result_does_not_delete(self, tmp_path):
        from ai.rag.converters.schemas import DocumentConversionResult

        fake_path = tmp_path / "not_created.pdf"
        failed_result = DocumentConversionResult(
            original_path=tmp_path / "a.hwp",
            converted_path=fake_path,
            original_file_type="hwp",
            success=False,
            converter_name="libreoffice-headless",
            error_message="변환 실패",
        )
        # 예외를 던지지 않아야 함 (파일이 없어도 안전)
        cleanup_converted_file(failed_result)


class TestConversionMetadata:
    def test_build_conversion_metadata_success(self, tmp_path):
        from ai.rag.converters.schemas import DocumentConversionResult

        result = DocumentConversionResult(
            original_path=tmp_path / "a.hwp",
            converted_path=tmp_path / "a_converted.pdf",
            original_file_type="hwp",
            converted_file_type="pdf",
            success=True,
            converter_name="libreoffice-headless",
            duration_ms=2480,
        )
        metadata = build_conversion_metadata(result)
        assert metadata.conversion_status == ConversionStatus.COMPLETED
        assert metadata.original_file_type == "hwp"
        assert metadata.processing_file_type == "pdf"
        assert metadata.conversion_error is None

    def test_build_conversion_metadata_failure(self, tmp_path):
        from ai.rag.converters.schemas import DocumentConversionResult

        result = DocumentConversionResult(
            original_path=tmp_path / "a.hwp",
            converted_path=tmp_path / "a_converted.pdf",
            original_file_type="hwp",
            success=False,
            converter_name="libreoffice-headless",
            error_message="변환 프로세스 실패",
        )
        metadata = build_conversion_metadata(result)
        assert metadata.conversion_status == ConversionStatus.FAILED
        assert metadata.conversion_error == "변환 프로세스 실패"


class TestSecurityPathHandling:
    def test_path_traversal_filename_does_not_escape_workdir(self, tmp_path):
        source_dir = tmp_path / "uploads"
        source_dir.mkdir()
        source = source_dir / "..%2f..%2fevil.hwp"
        _write_fake_hwp(source)
        converter = HwpPdfConverter(config=_config())
        output_dir = tmp_path / "work"

        with patch("ai.rag.converters.hwp_pdf_converter.subprocess.run", side_effect=_success_run_factory()):
            result = converter.convert(source, output_dir=output_dir)

        # 스테이징된 변환 대상은 항상 uuid 기반 이름이므로 원본 파일명이 명령/경로에 그대로 노출되지 않는다.
        assert Path(result.converted_path).parent == output_dir

    def test_special_character_filename_handled(self, tmp_path):
        source = _write_fake_hwp(tmp_path / "사업 계획서 (최종)!@#.hwp")
        converter = HwpPdfConverter(config=_config())

        with patch("ai.rag.converters.hwp_pdf_converter.subprocess.run", side_effect=_success_run_factory()):
            result = converter.convert(source, output_dir=tmp_path / "work")

        assert result.success is True

    def test_command_injection_like_filename_passed_as_single_argument(self, tmp_path):
        source = _write_fake_hwp(tmp_path / "a; rm -rf ~.hwp")
        converter = HwpPdfConverter(config=_config())
        captured = {}

        def _capture_and_succeed(command, **kwargs):
            captured["command"] = command
            return _success_run_factory()(command, **kwargs)

        with patch("ai.rag.converters.hwp_pdf_converter.subprocess.run", side_effect=_capture_and_succeed):
            converter.convert(source, output_dir=tmp_path / "work")

        # 위험한 파일명이 별도 리스트 원소로 전달되며 shell 문자열로 합쳐지지 않는다.
        assert all(isinstance(part, str) for part in captured["command"])

    def test_extension_mismatch_rejected(self, tmp_path):
        # .hwp 확장자이지만 실제로는 zip(hwpx류) 컨테이너인 위장 파일
        source = tmp_path / "fake.hwp"
        _write_fake_hwpx(source)
        converter = HwpPdfConverter(config=_config())
        with pytest.raises(InvalidSourceFileError):
            converter.convert(source)

    def test_oversized_file_not_converted(self, tmp_path):
        source = _write_fake_hwp(tmp_path / "a.hwp")
        converter = HwpPdfConverter(config=_config(max_file_size_bytes=1))
        with patch("ai.rag.converters.hwp_pdf_converter.subprocess.run") as mock_run:
            with pytest.raises(SourceFileTooLargeError):
                converter.convert(source)
            mock_run.assert_not_called()
