"""
HWP/HWPX -> PDF Converter (LibreOffice headless)
======================================================
LibreOffice의 `soffice --headless --convert-to pdf` CLI를 서브프로세스로 호출해
HWP(OLE 바이너리)/HWPX(ZIP+XML) 문서를 PDF로 변환한다. 변환된 PDF는 기존
`ai.rag.parsers.unified_parser.extract_document()`가 그대로 처리한다 — 이 모듈은
새 PDF 파서나 OCR을 만들지 않는다.

LibreOffice는 무료/오픈소스이며 headless(CLI, UI 없음) 실행과 --outdir 지정,
subprocess timeout이 모두 가능해 요건에 맞는다. 다만 HWP(바이너리)/HWPX(XML) 변환
품질은 문서 복잡도에 따라 달라질 수 있어, 실제 배포 서버(NCP)에서의 동작은 별도
검증이 필요하다 — 이 모듈은 변환기가 없거나 실패하면 성공한 것처럼 위장하지 않고
명시적 예외를 던진다.
"""

import logging
import shutil
import subprocess
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import Optional

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
from ai.rag.converters.schemas import DocumentConversionResult

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".hwp", ".hwpx"})

_CANDIDATE_EXECUTABLE_NAMES: tuple[str, ...] = ("soffice", "libreoffice", "soffice.exe")

# Windows에서 winget/공식 인스톨러로 LibreOffice를 설치해도 기본적으로 PATH에는
# 추가되지 않는다. 환경변수(HWP_CONVERTER_EXECUTABLE)도 PATH도 없을 때 마지막
# 수단으로 흔한 기본 설치 경로를 확인한다 — 환경변수로 명시된 경로가 항상 최우선이며
# 이 목록은 그 다음, PATH 탐색 다음 순서로만 쓰인다.
_WINDOWS_DEFAULT_INSTALL_PATHS: tuple[str, ...] = (
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
)

# Microsoft Compound File Binary Format(OLE2) 매직 넘버. HWP 5.0은 이 컨테이너 포맷을
# 그대로 사용한다. 다른 OLE 기반 포맷(예: 구버전 .doc/.xls)과 컨테이너 수준에서는
# 구분되지 않으므로, 확장자(.hwp)와 함께 최소한의 방어적 검증으로만 사용한다 —
# 스토리지 스트림 이름까지 검사하는 완전한 HWP 형식 검증은 전용 라이브러리(pyhwp 등)
# 없이는 하지 않는다.
_HWP_OLE_SIGNATURE: bytes = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

# HWPX는 ZIP 컨테이너(OOXML/OWPML과 유사한 ZIP+XML 구조)이므로 표준 ZIP local file
# header 시그니처로 1차 검증한 뒤 zipfile로 실제 컨테이너 무결성을 확인한다.
_ZIP_SIGNATURE: bytes = b"PK\x03\x04"

_PDF_MAGIC: bytes = b"%PDF-"

# 가은/Claude(2026-07-22, 용준 협의 — 동시 변환 실패 대응, 실측 재설계): HWP/HWPX 변환은
# 반드시 "기본 사용자 프로필"로 실행해야 한다 — HWP 필터(H2Orestart 확장)가 사용자
# 프로필 안에만 설치돼 있어서(`unopkg list --shared`는 비어 있음, 실측 2026-07-22),
# -env:UserInstallation으로 빈 격리 프로필을 주면 확장이 없어 soffice가 0xC0000409로
# 크래시한다(기본 프로필로는 같은 파일이 정상 변환되는 것을 4조합 매트릭스로 확인).
# 기존 사용자 프로필을 임시 복사하는 방식도 Windows MAX_PATH(260자) 제한에 걸려 기각.
#
# 대신 기본 프로필을 쓰는 soffice 호출은 "동시에 하나만" 실행되도록 이 락으로 직렬화한다
# — LibreOffice headless는 같은 프로필을 두 프로세스가 쓰면 나중 프로세스가 실패하기
# 때문이다(preview_pdf_converter.py의 재인 실측과 동일). 격리 프로필을 쓰는 호출(docx
# 미리보기, 기동 진단의 txt 프로브)은 프로필이 서로 달라 이 락과 무관하게 병렬로 돌 수
# 있다. preview_pdf_converter.py가 HWP/HWPX 미리보기를 변환할 때도 이 락을 함께 쓴다.
#
# 한계: ① 프로세스 내 락이라 uvicorn 워커가 여러 개면 서로를 못 막는다(현재 dev/배포
# 모두 단일 워커). ② 사용자가 LibreOffice 창을 열어두면(GUI도 기본 프로필 사용) HWP
# 변환이 실패할 수 있다. 근본 해결은 H2Orestart를 shared로 설치(`unopkg add --shared`,
# 관리자 권한 필요)한 뒤 격리 프로필로 되돌리는 것 — 팀 논의 필요.
SOFFICE_DEFAULT_PROFILE_LOCK = threading.Lock()


def looks_like_hwp(path: Path) -> bool:
    """OLE Compound File 시그니처 검사. 참이어도 HWP라는 완전한 보장은 아니다(컨테이너 수준 검증)."""
    try:
        with open(path, "rb") as f:
            header = f.read(len(_HWP_OLE_SIGNATURE))
    except OSError:
        return False
    return header == _HWP_OLE_SIGNATURE


def looks_like_hwpx(path: Path) -> bool:
    """ZIP 시그니처 + zipfile 무결성 검사."""
    try:
        with open(path, "rb") as f:
            header = f.read(len(_ZIP_SIGNATURE))
    except OSError:
        return False
    if header != _ZIP_SIGNATURE:
        return False
    try:
        return zipfile.is_zipfile(path)
    except OSError:
        return False


def _validate_source_signature(source_path: Path, extension: str) -> None:
    if extension == ".hwpx":
        if not looks_like_hwpx(source_path):
            raise InvalidSourceFileError(
                f"HWPX 파일 시그니처 검증 실패: {source_path.name}",
                user_message="HWPX 파일 형식이 올바르지 않거나 손상되었습니다.",
            )
    elif extension == ".hwp":
        if not looks_like_hwp(source_path):
            raise InvalidSourceFileError(
                f"HWP 파일 시그니처 검증 실패: {source_path.name}",
                user_message="HWP 파일 형식이 올바르지 않거나 손상되었습니다.",
            )
    else:
        raise UnsupportedConversionFormatError(f"지원하지 않는 변환 형식입니다: {extension}")


def _looks_like_pdf(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            header = f.read(len(_PDF_MAGIC))
    except OSError:
        return False
    return header == _PDF_MAGIC


def _truncate(text: Optional[str], limit: int = 300) -> str:
    if not text:
        return ""
    return text[:limit] + ("...(truncated)" if len(text) > limit else "")


def find_executable(configured_path: Optional[str]) -> Optional[str]:
    """실행 파일 경로를 결정한다. 명시적으로 설정된 경로가 있으면 존재 여부만 확인하고,
    없으면 PATH에서 soffice/libreoffice를 탐색한다. 못 찾으면 None(존재 여부를 숨기지 않음)."""
    if configured_path:
        return configured_path if Path(configured_path).exists() else None
    for name in _CANDIDATE_EXECUTABLE_NAMES:
        found = shutil.which(name)
        if found:
            return found
    for candidate in _WINDOWS_DEFAULT_INSTALL_PATHS:
        if Path(candidate).exists():
            return candidate
    return None


class HwpPdfConverter:
    """LibreOffice headless CLI로 HWP/HWPX -> PDF 변환을 수행하는 DocumentConverter 구현체."""

    name = "libreoffice-headless"

    def __init__(self, config: Optional[HwpConversionConfig] = None):
        self._config = config or HwpConversionConfig()

    def supports(self, source_path: Path) -> bool:
        return Path(source_path).suffix.lower() in SUPPORTED_EXTENSIONS

    def is_available(self) -> bool:
        return self._config.enabled and find_executable(self._config.executable_path) is not None

    def convert(
        self,
        source_path: Path,
        *,
        output_dir: Optional[Path] = None,
    ) -> DocumentConversionResult:
        source_path = Path(source_path)
        extension = source_path.suffix.lower()

        if extension not in SUPPORTED_EXTENSIONS:
            raise UnsupportedConversionFormatError(f"지원하지 않는 변환 형식입니다: {extension}")

        if not self._config.enabled:
            raise ConverterUnavailableError("HWP/HWPX 변환이 서버 설정에서 비활성화되어 있습니다.")

        if not source_path.exists():
            raise InvalidSourceFileError(
                f"원본 파일을 찾을 수 없습니다: {source_path.name}",
                user_message="문서 파일을 찾을 수 없습니다.",
            )

        file_size = source_path.stat().st_size
        if file_size == 0:
            raise InvalidSourceFileError(
                f"빈 파일입니다: {source_path.name}", user_message="내용이 없는 문서입니다."
            )
        if file_size > self._config.max_file_size_bytes:
            limit_mb = self._config.max_file_size_bytes // (1024 * 1024)
            raise SourceFileTooLargeError(
                f"파일 크기가 제한({limit_mb}MB)을 초과합니다: {file_size} bytes"
            )

        _validate_source_signature(source_path, extension)

        executable = find_executable(self._config.executable_path)
        if executable is None:
            raise ConverterUnavailableError(
                "HWP/HWPX 변환 도구(LibreOffice)를 찾을 수 없습니다. "
                "HWP_CONVERTER_EXECUTABLE 환경변수 또는 PATH를 확인하세요."
            )

        work_dir = self._resolve_work_dir(output_dir)
        work_dir.mkdir(parents=True, exist_ok=True)

        # LibreOffice는 원본 파일명(확장자 제외)을 그대로 출력 PDF명으로 쓴다.
        # 동시 요청 간 파일명 충돌과 path traversal을 막기 위해 원본 파일명을 신뢰하지 않고
        # 무작위 이름으로 복사한 뒤 그 사본을 변환한다.
        safe_stem = uuid.uuid4().hex
        staged_source = work_dir / f"{safe_stem}{extension}"
        shutil.copyfile(source_path, staged_source)

        # 기본 프로필로 실행한다(-env:UserInstallation 격리 금지 — H2Orestart가 사용자
        # 프로필에만 있어 격리 프로필에서는 크래시, SOFFICE_DEFAULT_PROFILE_LOCK 주석 참고).
        # 대신 아래 subprocess 호출을 락으로 직렬화해 기본 프로필 동시 사용을 막는다.
        command = [
            executable,
            "--headless",
            "--norestore",
            "--convert-to",
            "pdf",
            "--outdir",
            str(work_dir),
            str(staged_source),
        ]

        logger.info(
            "[DOCUMENT_CONVERSION_START] original_file_type=%s file_size=%d converter_name=%s",
            extension.lstrip("."),
            file_size,
            self.name,
        )

        start = time.monotonic()
        try:
            with SOFFICE_DEFAULT_PROFILE_LOCK:
                completed = subprocess.run(
                    command,
                    shell=False,
                    check=False,
                    timeout=self._config.timeout_seconds,
                    capture_output=True,
                    text=True,
                )
        except subprocess.TimeoutExpired as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            self._cleanup(staged_source)
            logger.warning(
                "[DOCUMENT_CONVERSION_FAILED] original_file_type=%s error_code=TIMEOUT duration_ms=%d",
                extension.lstrip("."),
                duration_ms,
            )
            raise ConversionTimeoutError(
                f"변환이 timeout_seconds={self._config.timeout_seconds}초를 초과했습니다."
            ) from exc

        duration_ms = int((time.monotonic() - start) * 1000)
        converted_path = work_dir / f"{safe_stem}.pdf"

        if completed.returncode != 0:
            self._cleanup(staged_source, converted_path)
            logger.warning(
                "[DOCUMENT_CONVERSION_FAILED] original_file_type=%s error_code=PROCESS_ERROR "
                "duration_ms=%d return_code=%d",
                extension.lstrip("."),
                duration_ms,
                completed.returncode,
            )
            raise ConversionProcessError(
                f"변환 프로세스가 종료 코드 {completed.returncode}로 실패했습니다: "
                f"{_truncate(completed.stderr)}"
            )

        self._cleanup(staged_source)

        if not converted_path.exists():
            logger.warning(
                "[DOCUMENT_CONVERSION_FAILED] original_file_type=%s error_code=OUTPUT_NOT_FOUND duration_ms=%d",
                extension.lstrip("."),
                duration_ms,
            )
            raise ConvertedFileNotFoundError("변환 프로세스는 종료됐지만 출력 PDF가 생성되지 않았습니다.")

        if converted_path.stat().st_size == 0:
            self._cleanup(converted_path)
            logger.warning(
                "[DOCUMENT_CONVERSION_FAILED] original_file_type=%s error_code=EMPTY_OUTPUT duration_ms=%d",
                extension.lstrip("."),
                duration_ms,
            )
            raise InvalidConvertedPdfError("변환된 PDF 파일이 0바이트입니다.")

        if not _looks_like_pdf(converted_path):
            self._cleanup(converted_path)
            logger.warning(
                "[DOCUMENT_CONVERSION_FAILED] original_file_type=%s error_code=INVALID_PDF duration_ms=%d",
                extension.lstrip("."),
                duration_ms,
            )
            raise InvalidConvertedPdfError("변환된 파일이 유효한 PDF 시그니처를 갖고 있지 않습니다.")

        final_path = self._rename_for_readability(converted_path, source_path, work_dir)

        logger.info(
            "[DOCUMENT_CONVERSION_COMPLETE] original_file_type=%s converted_file_type=pdf "
            "duration_ms=%d converted_size=%d",
            extension.lstrip("."),
            duration_ms,
            final_path.stat().st_size,
        )

        return DocumentConversionResult(
            original_path=source_path,
            converted_path=final_path,
            original_file_type=extension.lstrip("."),
            converted_file_type="pdf",
            success=True,
            converter_name=self.name,
            duration_ms=duration_ms,
        )

    def _resolve_work_dir(self, output_dir: Optional[Path]) -> Path:
        if output_dir is not None:
            return Path(output_dir)
        return self._config.resolve_temp_dir() / "hwp_conversion"

    @staticmethod
    def _rename_for_readability(converted_path: Path, source_path: Path, work_dir: Path) -> Path:
        """`{uuid}.pdf`를 `{원본_stem}_converted.pdf`로 바꿔 디버깅하기 쉽게 한다.
        이름은 내부 처리용일 뿐 사용자에게 노출되는 문서명(원본 HWP/HWPX 파일명)과는 무관하다.
        충돌하면 무작위 이름을 그대로 유지한다(실패해도 치명적이지 않음)."""
        candidate = work_dir / f"{source_path.stem}_converted.pdf"
        if candidate == converted_path or candidate.exists():
            return converted_path
        try:
            converted_path.rename(candidate)
            return candidate
        except OSError:
            return converted_path

    @staticmethod
    def _cleanup(*paths: Path) -> None:
        for path in paths:
            try:
                if path.exists():
                    path.unlink()
            except OSError as exc:
                logger.warning("[DOCUMENT_CONVERSION_CLEANUP_FAILED] path_name=%s error=%s", path.name, exc)



__all__ = [
    "HwpPdfConverter",
    "SUPPORTED_EXTENSIONS",
    "looks_like_hwp",
    "looks_like_hwpx",
    "find_executable",
]
