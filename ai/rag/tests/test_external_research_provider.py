"""
Unit Tests for ai.rag.external_research.providers (RAG-007)
==================================================================
실제 네트워크 호출이나 Chroma 서버 없이(임시 PersistentClient + mock fetch) 검증한다.
"""

import time

import pytest

from ai.rag.external_research.config import DEFAULT_COLLECTION_NAME, ExternalResearchConfig, PublicApiProviderConfig
from ai.rag.external_research.exceptions import ExternalProviderTimeoutError, ExternalProviderUnavailableError
from ai.rag.external_research.providers.dataset_provider import DatasetProvider
from ai.rag.external_research.providers.public_api_provider import PublicApiProvider
from ai.rag.external_research.repository import ExternalEvidenceRepository
from ai.rag.external_research.schemas import ExternalEvidenceDocument, ExternalEvidenceType, ExternalResearchRequest
from ai.rag.retrieval.chroma_store import create_persistent_client
from ai.rag.tests._external_research_fixtures import FakeEvidenceEmbedder

_DIM = 4


def _doc(document_id="DOC-001", chunk_id="CHUNK-001", domain="public_service", content="본문 내용입니다.", **overrides):
    base = dict(
        source_id="SRC-1",
        document_id=document_id,
        chunk_id=chunk_id,
        title="제목",
        evidence_type=ExternalEvidenceType.STATISTICS,
        publisher="통계청",
        source_url="https://example.org/data",
        domain=domain,
        content=content,
    )
    base.update(overrides)
    return ExternalEvidenceDocument(**base)


def _request(**overrides) -> ExternalResearchRequest:
    base = dict(domain="public_service", evaluation_criteria=["시장성"], reviewer_role="marketing", top_k=5)
    base.update(overrides)
    return ExternalResearchRequest(**base)


@pytest.fixture
def repository(tmp_path):
    client = create_persistent_client(path=str(tmp_path / "chroma_data"))
    return ExternalEvidenceRepository(
        client=client,
        collection_name=DEFAULT_COLLECTION_NAME,
        embedding_model="fake-external-research-embedder",
        embedding_dimension=_DIM,
        embedding_version="embedding_v1",
    )


class TestDatasetProvider:
    def test_normal_search_returns_candidates(self, repository):
        embedder = FakeEvidenceEmbedder(dimension=_DIM, overrides={"query": [1.0, 0.0, 0.0, 0.0], "본문 내용입니다.": [1.0, 0.0, 0.0, 0.0]})
        repository.upsert_evidence_chunk(_doc(), [1.0, 0.0, 0.0, 0.0])

        provider = DatasetProvider(repository, embedder)
        candidates = provider.search(_request(), "query")

        assert len(candidates) == 1
        assert candidates[0].retrieval_source == "dataset"
        assert candidates[0].verified_source is True

    def test_name_property(self, repository):
        embedder = FakeEvidenceEmbedder(dimension=_DIM)
        provider = DatasetProvider(repository, embedder)
        assert provider.name == "dataset"

    def test_no_results_returns_empty_list(self, repository):
        embedder = FakeEvidenceEmbedder(dimension=_DIM)
        provider = DatasetProvider(repository, embedder)
        assert provider.search(_request(), "query") == []

    def test_missing_evidence_type_excluded(self, repository):
        # metadata에서 evidence_type이 사라진 상황을 흉내내기 위해 낮은 레벨로 직접 upsert.
        from ai.rag.external_research.repository import build_evidence_record_id
        from ai.rag.retrieval.metadata import sanitize_metadata_for_chroma

        record_id = build_evidence_record_id("SRC-1", "DOC-BROKEN", "CHUNK-1")
        repository._collection.upsert(
            ids=[record_id],
            embeddings=[[1.0, 0.0, 0.0, 0.0]],
            documents=["내용"],
            metadatas=[sanitize_metadata_for_chroma({
                "source_id": "SRC-1", "document_id": "DOC-BROKEN", "chunk_id": "CHUNK-1",
                "title": "t", "publisher": "p", "source_url": "https://x", "domain": "public_service",
            })],
        )
        embedder = FakeEvidenceEmbedder(dimension=_DIM)
        provider = DatasetProvider(repository, embedder)
        candidates = provider.search(_request(), "query")
        assert candidates == []


class TestPublicApiProvider:
    def test_disabled_by_default_raises_unavailable(self, repository):
        provider = PublicApiProvider()
        with pytest.raises(ExternalProviderUnavailableError):
            provider.search(_request(), "query")

    def test_enabled_without_fetch_raises_unavailable(self):
        provider = PublicApiProvider(enabled=True)
        with pytest.raises(ExternalProviderUnavailableError):
            provider.search(_request(), "query")

    def test_mock_fetch_returns_candidates_without_network(self):
        def fake_fetch(request, query_text):
            return [{
                "source_id": "API-1", "document_id": "DOC-API-1", "chunk_id": "CHUNK-1",
                "title": "실시간 자료", "evidence_type": "market", "publisher": "산업통상자원부",
                "source_url": "https://example.gov/api-data", "domain": "public_service",
                "content": "실시간으로 수집된 시장 자료입니다.",
            }]

        provider = PublicApiProvider(fetch=fake_fetch, enabled=True)
        candidates = provider.search(_request(), "query")

        assert len(candidates) == 1
        assert candidates[0].retrieval_source == "public_api"
        assert candidates[0].source_url == "https://example.gov/api-data"

    def test_timeout_raises_timeout_error(self):
        def slow_fetch(request, query_text):
            time.sleep(0.5)
            return []

        provider = PublicApiProvider(
            fetch=slow_fetch, enabled=True, config=PublicApiProviderConfig(timeout_seconds=0.05)
        )
        with pytest.raises(ExternalProviderTimeoutError):
            provider.search(_request(), "query")

    def test_fetch_exception_raises_unavailable_not_crashes(self):
        def broken_fetch(request, query_text):
            raise RuntimeError("공공데이터 포털 연결 실패")

        provider = PublicApiProvider(fetch=broken_fetch, enabled=True)
        with pytest.raises(ExternalProviderUnavailableError):
            provider.search(_request(), "query")

    def test_result_without_source_url_excluded(self):
        def fetch_missing_source(request, query_text):
            return [{
                "source_id": "API-2", "document_id": "DOC-API-2", "chunk_id": "CHUNK-1",
                "title": "출처 없는 자료", "evidence_type": "market", "publisher": "p",
                "source_url": "", "domain": "d", "content": "내용",
            }]

        provider = PublicApiProvider(fetch=fetch_missing_source, enabled=True)
        candidates = provider.search(_request(), "query")
        assert len(candidates) == 1
        assert candidates[0].verified_source is False  # 최종 제외는 search_service 책임

    def test_result_without_publisher_flagged_unverified(self):
        def fetch_missing_publisher(request, query_text):
            return [{
                "source_id": "API-3", "document_id": "DOC-API-3", "chunk_id": "CHUNK-1",
                "title": "발행기관 없는 자료", "evidence_type": "market", "publisher": "",
                "source_url": "https://example.gov/x", "domain": "d", "content": "내용",
            }]

        provider = PublicApiProvider(fetch=fetch_missing_publisher, enabled=True)
        candidates = provider.search(_request(), "query")
        assert candidates[0].verified_source is False

    def test_unknown_evidence_type_excluded(self):
        def fetch_bad_type(request, query_text):
            return [{
                "source_id": "API-4", "document_id": "DOC-API-4", "chunk_id": "CHUNK-1",
                "title": "t", "evidence_type": "not_a_real_type", "publisher": "p",
                "source_url": "https://example.gov/x", "domain": "d", "content": "내용",
            }]

        provider = PublicApiProvider(fetch=fetch_bad_type, enabled=True)
        candidates = provider.search(_request(), "query")
        assert candidates == []

    def test_max_results_limit_applied(self):
        def fetch_many(request, query_text):
            return [
                {
                    "source_id": f"API-{i}", "document_id": f"DOC-{i}", "chunk_id": "CHUNK-1",
                    "title": "t", "evidence_type": "market", "publisher": "p",
                    "source_url": "https://example.gov/x", "domain": "d", "content": "내용",
                }
                for i in range(20)
            ]

        provider = PublicApiProvider(
            fetch=fetch_many, enabled=True, config=PublicApiProviderConfig(max_results=3)
        )
        candidates = provider.search(_request(), "query")
        assert len(candidates) == 3

    def test_no_real_network_call_made(self):
        """fetch가 순수 mock이므로 이 테스트 스위트 전체가 실제 네트워크를 쓰지 않는다 —
        provider가 fetch 콜러블 이외의 방식으로 네트워크에 접근하지 않는지 소스 검사로 재확인."""
        import inspect

        from ai.rag.external_research.providers import public_api_provider

        source = inspect.getsource(public_api_provider)
        for forbidden in ("requests.", "httpx.", "urllib.request", "http.client"):
            assert forbidden not in source
