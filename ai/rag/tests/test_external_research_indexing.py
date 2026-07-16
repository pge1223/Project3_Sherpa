"""
Unit Tests for ai.rag.external_research.indexing_service (RAG-007)
=========================================================================
"""

import pytest

from ai.rag.external_research.config import DEFAULT_COLLECTION_NAME
from ai.rag.external_research.exceptions import ExternalEvidenceIndexingError
from ai.rag.external_research.indexing_service import ExternalEvidenceIndexingService
from ai.rag.external_research.repository import ExternalEvidenceRepository
from ai.rag.external_research.schemas import ExternalEvidenceDocument, ExternalEvidenceType
from ai.rag.retrieval.chroma_store import create_persistent_client
from ai.rag.tests._external_research_fixtures import FakeEvidenceEmbedder

_DIM = 4


def _doc(source_id="KOSIS-POP-2025", document_id="DOC-001", chunk_id="CHUNK-001", **overrides) -> ExternalEvidenceDocument:
    base = dict(
        source_id=source_id,
        document_id=document_id,
        chunk_id=chunk_id,
        title="연령별 인구 통계",
        evidence_type=ExternalEvidenceType.STATISTICS,
        publisher="통계청",
        source_url="https://kosis.kr/example",
        domain="public_service",
        content="2025년 12월 기준 전국 인구는 5,170만 명입니다.",
    )
    base.update(overrides)
    return ExternalEvidenceDocument(**base)


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


@pytest.fixture
def embedder():
    return FakeEvidenceEmbedder(dimension=_DIM)


class TestIndexEvidence:
    def test_indexes_into_external_collection(self, repository, embedder):
        service = ExternalEvidenceIndexingService(repository, embedder)
        summary = service.index_evidence([_doc()])

        assert summary.indexed_count == 1
        assert summary.collection_name == DEFAULT_COLLECTION_NAME
        assert repository.count() == 1

    def test_separated_from_project_and_case_collections(self, repository, embedder):
        from ai.rag.domain.config import DEFAULT_COLLECTION_NAME as PROJECT_DOCS_COLLECTION
        from ai.rag.similar_cases.config import DEFAULT_COLLECTION_NAME as CASES_COLLECTION

        client = repository._client
        service = ExternalEvidenceIndexingService(repository, embedder)
        service.index_evidence([_doc()])

        collection_names = [c.name for c in client.list_collections()]
        assert DEFAULT_COLLECTION_NAME in collection_names
        assert PROJECT_DOCS_COLLECTION not in collection_names
        assert CASES_COLLECTION not in collection_names

    def test_required_metadata_stored(self, repository, embedder):
        service = ExternalEvidenceIndexingService(repository, embedder)
        service.index_evidence([_doc(evaluation_criteria=["시장성"], supported_roles=["marketing"])])

        hits = repository.search(embedder.embed_query("2025년 12월 기준 전국 인구는 5,170만 명입니다."), top_k=5)
        assert hits[0].metadata["publisher"] == "통계청"
        assert hits[0].metadata["evaluation_criteria"] == ["시장성"]
        assert hits[0].metadata["supported_roles"] == ["marketing"]

    def test_blank_content_skipped_defensively(self, repository, embedder):
        """빈 content는 이미 ExternalEvidenceDocument 생성 시점에 거부되므로, 여기서는
        pydantic 검증을 우회한 legacy 데이터를 방어적으로 건너뛰는지 확인한다."""
        service = ExternalEvidenceIndexingService(repository, embedder)
        blank_doc = ExternalEvidenceDocument.model_construct(**{**_doc().model_dump(), "content": "   "})

        summary = service.index_evidence([blank_doc])
        assert summary.indexed_count == 0
        assert summary.skipped_count == 1
        assert any("content가 비어" in w for w in summary.warnings)

    def test_document_without_source_rejected_at_indexing(self, repository, embedder):
        """source_url이 빈 문자열이면 스키마 단계에서 이미 거부되지만, 색인 서비스가
        source_validator로 한 번 더 방어하는지 legacy 데이터로 확인한다."""
        service = ExternalEvidenceIndexingService(repository, embedder)
        sourceless_doc = ExternalEvidenceDocument.model_construct(**{**_doc().model_dump(), "source_url": ""})

        summary = service.index_evidence([sourceless_doc])
        assert summary.indexed_count == 0
        assert summary.skipped_count == 1
        assert any("출처 검증 실패" in w for w in summary.warnings)

    def test_partial_batch_failure_does_not_abort_others(self, repository, embedder):
        service = ExternalEvidenceIndexingService(repository, embedder)
        valid_doc = _doc(chunk_id="CHUNK-001")
        blank_doc = ExternalEvidenceDocument.model_construct(
            **{**_doc(chunk_id="CHUNK-002").model_dump(), "content": ""}
        )
        summary = service.index_evidence([valid_doc, blank_doc])

        assert summary.indexed_count == 1
        assert summary.skipped_count == 1
        assert repository.count() == 1

    def test_reindexing_same_record_does_not_duplicate(self, repository, embedder):
        service = ExternalEvidenceIndexingService(repository, embedder)
        service.index_evidence([_doc()])
        service.index_evidence([_doc(content="갱신된 내용입니다.")])

        assert repository.count() == 1

    def test_total_input_count_reported(self, repository, embedder):
        service = ExternalEvidenceIndexingService(repository, embedder)
        blank_doc = ExternalEvidenceDocument.model_construct(
            **{**_doc(chunk_id="CHUNK-002").model_dump(), "content": ""}
        )
        summary = service.index_evidence([_doc(chunk_id="CHUNK-001"), blank_doc])
        assert summary.total_input_count == 2

    def test_indexing_error_wraps_unexpected_exception(self, embedder):
        class _BrokenRepository:
            collection_name = DEFAULT_COLLECTION_NAME

            def upsert_evidence_chunk(self, document, embedding):
                raise RuntimeError("chroma 연결 끊김")

        service = ExternalEvidenceIndexingService(_BrokenRepository(), embedder)
        with pytest.raises(ExternalEvidenceIndexingError):
            service.index_evidence([_doc()])


class TestMissingSourceRejectedAtSchemaLevel:
    def test_blank_source_url_rejected(self):
        from ai.rag.external_research.exceptions import ExternalResearchValidationError

        with pytest.raises(ExternalResearchValidationError):
            _doc(source_url="")

    def test_blank_publisher_rejected(self):
        from ai.rag.external_research.exceptions import ExternalResearchValidationError

        with pytest.raises(ExternalResearchValidationError):
            _doc(publisher="")
