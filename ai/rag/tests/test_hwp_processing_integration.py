"""
Integration-style Tests: HWP -> PDF Converter -> Existing PDF Parser
==========================================================================
backend/app/api/routes/documents.py는 이번 작업 범위(윤한 담당)가 아니라서 직접
테스트하지 못한다. 대신 ai/rag 계층 안에서 convert_if_needed() -> extract_document()
로 이어지는 실제 처리 경로가 새 PDF 파서/OCR 없이 기존 ai.rag.parsers를 그대로
재사용하는지 PyMuPDF로 생성한 실제 PDF를 사용해 검증한다(LibreOffice 실행 파일은
subprocess.run mock으로 대체).
"""

import subprocess
from pathlib import Path
from unittest.mock import patch

import fitz
import pytest

from ai.rag.converters.config import HwpConversionConfig
from ai.rag.converters.factory import convert_if_needed
from ai.rag.parsers.unified_parser import extract_document

_HWP_OLE_HEADER = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 32


def _write_fake_hwp(path: Path) -> Path:
    path.write_bytes(_HWP_OLE_HEADER)
    return path


def _make_real_pdf(path: Path, text: str = "Budget plan and schedule guidance document.") -> None:
    # PyMuPDF의 Base-14 내장 폰트(Helvetica)는 한글 글리프를 지원하지 않아 한글 문자열을
    # insert_text()로 넣으면 실제 콘텐츠 스트림에 텍스트가 남지 않는다(파이프라인 배선을
    # 검증하는 게 목적이라 ASCII로 대체 — 실제 한글 렌더링 검증은 LibreOffice가 만든
    # 진짜 변환 PDF로 별도 수동 검증이 필요하다).
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    doc.save(str(path))
    doc.close()


def _fake_libreoffice_run(command, **kwargs):
    outdir = Path(command[command.index("--outdir") + 1])
    staged = Path(command[-1])
    _make_real_pdf(outdir / f"{staged.stem}.pdf")
    return subprocess.CompletedProcess(command, returncode=0, stdout="", stderr="")


def _config() -> HwpConversionConfig:
    return HwpConversionConfig(enabled=True, executable_path=None)


@pytest.fixture(autouse=True)
def _default_executable_lookup(monkeypatch):
    """이 환경에는 LibreOffice가 설치되어 있지 않으므로 PATH 탐색 결과를 가짜 경로로 고정한다."""
    monkeypatch.setattr(
        "ai.rag.converters.hwp_pdf_converter.shutil.which", lambda name: "/usr/bin/soffice"
    )


class TestHwpToPdfParserIntegration:
    def test_converted_pdf_parsed_by_existing_pdf_parser(self, tmp_path):
        source = _write_fake_hwp(tmp_path / "사업계획서.hwp")

        with patch("ai.rag.converters.hwp_pdf_converter.subprocess.run", side_effect=_fake_libreoffice_run):
            result = convert_if_needed(source, output_dir=tmp_path / "work", config=_config())

        assert result is not None
        assert result.success is True

        extraction = extract_document(result.converted_path)
        assert extraction.block_count > 0
        assert extraction.file_type.value == "pdf"
        assert any("Budget" in block.content for block in extraction.blocks)

    def test_extract_document_reports_converted_filename_not_original(self, tmp_path):
        """extract_document()는 전달받은 경로(변환된 PDF) 기준 파일명을 반환한다 — 호출자가
        문서 저장 시 원본 HWP 파일명으로 덮어써야 함을 문서화하는 테스트 (INTEGRATION.md 4번)."""
        source = _write_fake_hwp(tmp_path / "사업계획서.hwp")

        with patch("ai.rag.converters.hwp_pdf_converter.subprocess.run", side_effect=_fake_libreoffice_run):
            result = convert_if_needed(source, output_dir=tmp_path / "work", config=_config())

        extraction = extract_document(result.converted_path)
        assert extraction.file_name == Path(result.converted_path).name
        assert extraction.file_name != source.name

    def test_original_hwp_file_untouched_after_full_flow(self, tmp_path):
        source = _write_fake_hwp(tmp_path / "a.hwp")
        original_bytes = source.read_bytes()

        with patch("ai.rag.converters.hwp_pdf_converter.subprocess.run", side_effect=_fake_libreoffice_run):
            result = convert_if_needed(source, output_dir=tmp_path / "work", config=_config())
        extract_document(result.converted_path)

        assert source.read_bytes() == original_bytes
        assert source.suffix == ".hwp"

    def test_hwpx_also_routes_through_converter(self, tmp_path):
        import zipfile

        source = tmp_path / "공모전.hwpx"
        with zipfile.ZipFile(source, "w") as zf:
            zf.writestr("Contents/content.hpf", "<xml/>")

        with patch("ai.rag.converters.hwp_pdf_converter.subprocess.run", side_effect=_fake_libreoffice_run):
            result = convert_if_needed(source, output_dir=tmp_path / "work", config=_config())

        assert result is not None
        assert result.original_file_type == "hwpx"
        extraction = extract_document(result.converted_path)
        assert extraction.block_count > 0

    def test_pdf_bypasses_converter_entirely(self, tmp_path):
        pdf_path = tmp_path / "a.pdf"
        _make_real_pdf(pdf_path)

        assert convert_if_needed(pdf_path) is None

        extraction = extract_document(pdf_path)
        assert extraction.file_name == "a.pdf"

    def test_docx_bypasses_converter_entirely(self, tmp_path):
        pytest.importorskip("docx")
        from docx import Document

        docx_path = tmp_path / "a.docx"
        doc = Document()
        doc.add_paragraph("예산 계획 문서")
        doc.save(str(docx_path))

        assert convert_if_needed(docx_path) is None

    def test_no_new_ocr_engine_created_for_converted_pdf(self, tmp_path):
        """변환된 PDF도 기존 PDFParser의 lazy OCR 초기화 경로를 그대로 타는지 확인 —
        HWP 전용 OCR 로직이 새로 생기지 않았음을 보장한다."""
        source = _write_fake_hwp(tmp_path / "a.hwp")

        with patch("ai.rag.converters.hwp_pdf_converter.subprocess.run", side_effect=_fake_libreoffice_run):
            result = convert_if_needed(source, output_dir=tmp_path / "work", config=_config())

        from ai.rag.parsers.pdf_parser import PDFParser

        parser = PDFParser(str(result.converted_path))
        # 텍스트 레이어가 있는 PDF이므로 OCR 엔진을 아직 초기화하지 않은 상태에서도 파싱이 끝나야 한다.
        extraction = parser.parse()
        assert extraction.requires_ocr is False
