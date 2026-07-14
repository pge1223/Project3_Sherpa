"""
Pytest Configuration and Fixtures
=================================
"""

import os
import sys
from pathlib import Path

import pytest

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))


def pytest_configure(config):
    """Pytest 커스텀 마커 등록"""
    config.addinivalue_line(
        "markers", "ocr: 스캔 PDF OCR 통합 테스트 (실제 EasyOCR 모델 사용)"
    )
    config.addinivalue_line(
        "markers", "slow: 실행 시간이 오래 걸리는 테스트"
    )


@pytest.fixture
def fixtures_dir() -> Path:
    """테스트 픽스처 디렉토리 경로"""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_pdf(fixtures_dir: Path) -> Path:
    """테스트용 PDF 파일 경로"""
    return fixtures_dir / "sample.pdf"


@pytest.fixture
def sample_docx(fixtures_dir: Path) -> Path:
    """테스트용 DOCX 파일 경로"""
    return fixtures_dir / "sample.docx"


@pytest.fixture
def sample_pptx(fixtures_dir: Path) -> Path:
    """테스트용 PPTX 파일 경로"""
    return fixtures_dir / "sample.pptx"


@pytest.fixture
def empty_pdf(fixtures_dir: Path) -> Path:
    """빈 PDF 파일 경로"""
    return fixtures_dir / "empty.pdf"


@pytest.fixture
def corrupted_file(fixtures_dir: Path) -> Path:
    """손상된 파일 경로"""
    return fixtures_dir / "corrupted.pdf"


@pytest.fixture
def large_file(fixtures_dir: Path) -> Path:
    """큰 파일 (20MB 초과 - 모의)"""
    return fixtures_dir / "large_file.pdf"


@pytest.fixture
def txt_file(fixtures_dir: Path) -> Path:
    """텍스트 파일 (지원하지 않는 형식)"""
    return fixtures_dir / "sample.txt"


@pytest.fixture
def scanned_pdf(fixtures_dir: Path) -> Path:
    """스캔 PDF 파일 (테스트용)"""
    return fixtures_dir / "test2.pdf"


@pytest.fixture
def ocr_engine():
    """테스트용 EasyOCR 엔진 (lazy initialization, 모델 다운로드 안 함)"""
    try:
        from ai.rag.parsers.easyocr_engine import EasyOCR
        ocr = EasyOCR(languages=["ko", "en"], gpu=False, download_enabled=False)
        if ocr.is_available():
            return ocr
        return None
    except ImportError:
        return None
