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
    config.addinivalue_line(
        "markers", "embedding_integration: 실제 KURE-v1 모델을 로딩하는 통합 테스트 (RUN_KURE_INTEGRATION=1로만 실행)"
    )
    config.addinivalue_line(
        "markers",
        "url_integration: 실제 URL 네트워크 요청 + 실제 KURE-v1 모델을 사용하는 fetch-url 색인 통합 테스트 "
        "(RUN_URL_INTEGRATION=1로만 실행)",
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
def sample_jpeg(fixtures_dir: Path) -> Path:
    """테스트용 JPEG 파일 경로 (공고 포스터 이미지 지원 테스트용)"""
    return fixtures_dir / "sample_poster.jpg"


@pytest.fixture
def sample_png_icon(fixtures_dir: Path) -> Path:
    """테스트용 작은 PNG 파일 경로 (로고/아이콘 노이즈 필터 테스트용, 10x10px)"""
    return fixtures_dir / "sample_icon.png"


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
def fake_kure_embedder(monkeypatch):
    """실제 KURE-v1을 로딩하지 않고 결정적 가짜 벡터를 반환하는 KUREEmbedder"""
    from ai.rag.tests.embedding_fixtures import FakeSentenceTransformer
    monkeypatch.setattr("ai.rag.embedding.kure_embedder.SentenceTransformer", FakeSentenceTransformer)

    from ai.rag.embedding import KUREEmbedder, EmbeddingConfig
    return KUREEmbedder(EmbeddingConfig(model_name="fake-model-for-tests"))


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
