"""
Unit Tests for ai.rag.external_research.repository (실제 chromadb PersistentClient +
tmp_path 사용, KURE-v1은 로딩하지 않음)
"""

import pytest

from ai.rag.domain.config import DEFAULT_COLLECTION_NAME as PROJECT_DOCUMENTS_COLLECTION
from ai.rag.external_research.config import DEFAULT_COLLECTION_NAME as EXTERNAL_COLLECTION_DEFAULT
from ai.rag.external_research.exceptions import ExternalCollectionUnavailableError
from ai.rag.external_research.repository import ExternalEvidenceRepository, build_evidence_record_id
from ai.rag.external_research.schemas import ExternalEvidenceDocument, ExternalEvidenceType
from ai.rag.retrieval.chroma_store import create_persistent_client
from ai.rag.similar_cases.config import DEFAULT_COLLECTION_NAME as SIMILAR_CASES_COLLECTION

_DIM = 4


def _doc(
    source_id="KOSIS-POP-2025",
    document_id="DOC-001",
    chunk_id="CHUNK-001",
    domain="public_service",
    content="2025년 12월 기준 전국 인구는 5,170만 명입니다.",
    **overrides,
) -> ExternalEvidenceDocument:
    base = dict(
        source_id=source_id,
        document_id=document_id,
        chunk_id=chunk_id,
        title="연령별 인구 통계",
        evidence_type=ExternalEvidenceType.STATISTICS,
        publisher="통계청",
        source_url="https://kosis.kr/example",
        domain=domain,
        evaluation_criteria=["시장성", "사회적 가치"],
        supported_roles=["marketing", "planning"],
        content=content,
        reference_date="2025-12-31",
        region="대한민국",
    )
    base.update(overrides)
    return ExternalEvidenceDocument(**base)


@pytest.fixture
def repository(tmp_path):
    client = create_persistent_client(path=str(tmp_path / "chroma_data"))
    return ExternalEvidenceRepository(
        client=client,
        collection_name=EXTERNAL_COLLECTION_DEFAULT,
        embedding_model="fake-external-research-embedder",
        embedding_dimension=_DIM,
        embedding_version="embedding_v1",
    )


class TestCollectionSeparation:
    def test_collection_name_distinct_from_other_collections(self, repository):
        assert repository.collection_name == EXTERNAL_COLLECTION_DEFAULT
        assert repository.collection_name != PROJECT_DOCUMENTS_COLLECTION
        assert repository.collection_name != SIMILAR_CASES_COLLECTION

    def test_custom_collection_name_used(self, tmp_path):
        client = create_persistent_client(path=str(tmp_path / "chroma_data"))
        repo = ExternalEvidenceRepository(
            client=client,
            collection_name="my_custom_external_evidence",
            embedding_model="fake-external-research-embedder",
            embedding_dimension=_DIM,
            embedding_version="embedding_v1",
        )
        assert repo.collection_name == "my_custom_external_evidence"


class TestUpsert:
    def test_upsert_stores_required_metadata(self, repository):
        doc = _doc()
        record_id = repository.upsert_evidence_chunk(doc, [0.1, 0.2, 0.3, 0.4])

        assert record_id == build_evidence_record_id(doc.source_id, doc.document_id, doc.chunk_id)
        got = repository._collection.get(ids=[record_id])
        metadata = got["metadatas"][0]
        assert metadata["source_id"] == "KOSIS-POP-2025"
        assert metadata["title"] == "연령별 인구 통계"
        assert metadata["publisher"] == "통계청"
        assert metadata["source_url"] == "https://kosis.kr/example"
        assert metadata["domain"] == "public_service"
        assert metadata["evidence_type"] == "statistics"

    def test_list_metadata_round_trips(self, repository):
        doc = _doc()
        repository.upsert_evidence_chunk(doc, [0.1, 0.2, 0.3, 0.4])

        hits = repository.search([0.1, 0.2, 0.3, 0.4], top_k=5)
        assert hits[0].metadata["evaluation_criteria"] == ["시장성", "사회적 가치"]
        assert hits[0].metadata["supported_roles"] == ["marketing", "planning"]

    def test_duplicate_record_id_overwrites_not_duplicates(self, repository):
        doc_v1 = _doc(content="첫 번째 버전 내용입니다.")
        doc_v2 = _doc(content="갱신된 두 번째 버전 내용입니다.")

        repository.upsert_evidence_chunk(doc_v1, [0.1, 0.2, 0.3, 0.4])
        repository.upsert_evidence_chunk(doc_v2, [0.5, 0.6, 0.7, 0.8])

        assert repository.count() == 1
        record_id = build_evidence_record_id(doc_v2.source_id, doc_v2.document_id, doc_v2.chunk_id)
        got = repository._collection.get(ids=[record_id])
        assert got["documents"][0] == "갱신된 두 번째 버전 내용입니다."

    def test_same_source_multiple_chunks_stored_separately(self, repository):
        chunk1 = _doc(chunk_id="CHUNK-001", content="첫 번째 청크")
        chunk2 = _doc(chunk_id="CHUNK-002", content="두 번째 청크")

        repository.upsert_evidence_chunk(chunk1, [0.1, 0.2, 0.3, 0.4])
        repository.upsert_evidence_chunk(chunk2, [0.2, 0.3, 0.4, 0.5])

        assert repository.count() == 2


class TestSearch:
    def test_domain_filter_applied(self, repository):
        repository.upsert_evidence_chunk(
            _doc(document_id="d-fin", domain="finance"), [1.0, 0.0, 0.0, 0.0]
        )
        repository.upsert_evidence_chunk(
            _doc(document_id="d-pub", domain="public_service"), [0.0, 1.0, 0.0, 0.0]
        )

        hits = repository.search([1.0, 0.0, 0.0, 0.0], domain="finance", top_k=5)
        assert len(hits) == 1
        assert hits[0].metadata["domain"] == "finance"

    def test_no_domain_filter_returns_all(self, repository):
        repository.upsert_evidence_chunk(
            _doc(document_id="d-fin", domain="finance"), [1.0, 0.0, 0.0, 0.0]
        )
        repository.upsert_evidence_chunk(
            _doc(document_id="d-pub", domain="public_service"), [0.0, 1.0, 0.0, 0.0]
        )

        hits = repository.search([1.0, 0.0, 0.0, 0.0], top_k=5)
        assert len(hits) == 2

    def test_evidence_type_filter_applied(self, repository):
        repository.upsert_evidence_chunk(
            _doc(document_id="d-stat", evidence_type=ExternalEvidenceType.STATISTICS), [1.0, 0.0, 0.0, 0.0]
        )
        repository.upsert_evidence_chunk(
            _doc(document_id="d-law", evidence_type=ExternalEvidenceType.LAW), [1.0, 0.0, 0.0, 0.0]
        )

        hits = repository.search(
            [1.0, 0.0, 0.0, 0.0], evidence_types=[ExternalEvidenceType.LAW], top_k=5
        )
        assert len(hits) == 1
        assert hits[0].metadata["evidence_type"] == "law"

    def test_domain_and_evidence_type_filter_combined(self, repository):
        repository.upsert_evidence_chunk(
            _doc(document_id="d-match", domain="finance", evidence_type=ExternalEvidenceType.MARKET),
            [1.0, 0.0, 0.0, 0.0],
        )
        repository.upsert_evidence_chunk(
            _doc(document_id="d-wrong-domain", domain="public_service", evidence_type=ExternalEvidenceType.MARKET),
            [1.0, 0.0, 0.0, 0.0],
        )
        repository.upsert_evidence_chunk(
            _doc(document_id="d-wrong-type", domain="finance", evidence_type=ExternalEvidenceType.LAW),
            [1.0, 0.0, 0.0, 0.0],
        )

        hits = repository.search(
            [1.0, 0.0, 0.0, 0.0], domain="finance", evidence_types=[ExternalEvidenceType.MARKET], top_k=5
        )
        assert len(hits) == 1
        assert hits[0].document_id == "d-match"

    def test_search_result_content_and_score_present(self, repository):
        doc = _doc()
        repository.upsert_evidence_chunk(doc, [1.0, 0.0, 0.0, 0.0])

        hits = repository.search([1.0, 0.0, 0.0, 0.0], top_k=5)
        assert hits[0].content == doc.content
        assert hits[0].score is not None
        assert hits[0].score > 0.9  # 동일 벡터이므로 cosine distance ~0, score ~1


class TestCollectionMismatch:
    def test_embedding_dimension_mismatch_raises(self, tmp_path):
        client = create_persistent_client(path=str(tmp_path / "chroma_data"))
        ExternalEvidenceRepository(
            client=client,
            collection_name=EXTERNAL_COLLECTION_DEFAULT,
            embedding_model="fake-external-research-embedder",
            embedding_dimension=4,
            embedding_version="embedding_v1",
        )
        with pytest.raises(ExternalCollectionUnavailableError):
            ExternalEvidenceRepository(
                client=client,
                collection_name=EXTERNAL_COLLECTION_DEFAULT,
                embedding_model="fake-external-research-embedder",
                embedding_dimension=8,
                embedding_version="embedding_v1",
            )
