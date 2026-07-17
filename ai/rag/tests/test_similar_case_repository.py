"""
Unit Tests for ai.rag.similar_cases.repository (실제 chromadb PersistentClient +
tmp_path 사용, KURE-v1은 로딩하지 않음)
"""

import pytest

from ai.rag.domain.config import DEFAULT_COLLECTION_NAME as PROJECT_DOCUMENTS_COLLECTION
from ai.rag.retrieval.chroma_store import create_persistent_client
from ai.rag.similar_cases.config import DEFAULT_COLLECTION_NAME as CASES_COLLECTION_DEFAULT
from ai.rag.similar_cases.exceptions import SimilarCaseCollectionUnavailableError
from ai.rag.similar_cases.repository import SimilarCaseRepository, build_case_record_id
from ai.rag.similar_cases.schemas import SimilarCaseDocument, SimilarCaseType
from ai.rag.tests._similar_case_fixtures import FakeCaseEmbedder

_DIM = 4


def _case(
    case_id="CASE-001",
    document_id="DOC-CASE-001",
    chunk_id="CHUNK-001",
    domain="public_service",
    content="본 서비스는 공공데이터를 활용해 문서를 자동 평가합니다.",
    **overrides,
) -> SimilarCaseDocument:
    base = dict(
        case_id=case_id,
        title="공공데이터 활용 공모전 수상작",
        case_type=SimilarCaseType.AWARD_WINNER,
        domain=domain,
        evaluation_criteria=["문제 정의", "기술성", "사업성"],
        source_name="공모전 공식 홈페이지",
        source_url="https://example.org/award/001",
        document_id=document_id,
        chunk_id=chunk_id,
        content=content,
        page=3,
        section="서비스 구성",
    )
    base.update(overrides)
    return SimilarCaseDocument(**base)


@pytest.fixture
def repository(tmp_path):
    client = create_persistent_client(path=str(tmp_path / "chroma_data"))
    return SimilarCaseRepository(
        client=client,
        collection_name=CASES_COLLECTION_DEFAULT,
        embedding_model="fake-case-embedder",
        embedding_dimension=_DIM,
        embedding_version="embedding_v1",
    )


class TestCollectionSeparation:
    def test_collection_name_distinct_from_project_documents(self, repository):
        assert repository.collection_name == CASES_COLLECTION_DEFAULT
        assert repository.collection_name != PROJECT_DOCUMENTS_COLLECTION

    def test_custom_collection_name_used(self, tmp_path):
        client = create_persistent_client(path=str(tmp_path / "chroma_data"))
        repo = SimilarCaseRepository(
            client=client,
            collection_name="my_custom_cases",
            embedding_model="fake-case-embedder",
            embedding_dimension=_DIM,
            embedding_version="embedding_v1",
        )
        assert repo.collection_name == "my_custom_cases"


class TestUpsert:
    def test_upsert_stores_required_metadata(self, repository):
        case = _case()
        record_id = repository.upsert_case_chunk(case, [0.1, 0.2, 0.3, 0.4])

        assert record_id == build_case_record_id(case.document_id, case.chunk_id)
        got = repository._collection.get(ids=[record_id])
        metadata = got["metadatas"][0]
        assert metadata["case_id"] == "CASE-001"
        assert metadata["title"] == "공공데이터 활용 공모전 수상작"
        assert metadata["domain"] == "public_service"
        assert metadata["source_name"] == "공모전 공식 홈페이지"
        assert metadata["source_url"] == "https://example.org/award/001"
        assert metadata["document_id"] == "DOC-CASE-001"
        assert metadata["chunk_id"] == "CHUNK-001"

    def test_evaluation_criteria_round_trips_as_list(self, repository):
        case = _case()
        repository.upsert_case_chunk(case, [0.1, 0.2, 0.3, 0.4])

        hits = repository.search([0.1, 0.2, 0.3, 0.4], top_k=5)
        assert hits[0].metadata["evaluation_criteria"] == ["문제 정의", "기술성", "사업성"]

    def test_duplicate_document_and_chunk_id_overwrites_not_duplicates(self, repository):
        case_v1 = _case(content="첫 번째 버전 내용입니다.")
        case_v2 = _case(content="갱신된 두 번째 버전 내용입니다.")

        repository.upsert_case_chunk(case_v1, [0.1, 0.2, 0.3, 0.4])
        repository.upsert_case_chunk(case_v2, [0.5, 0.6, 0.7, 0.8])

        assert repository.count() == 1
        record_id = build_case_record_id(case_v2.document_id, case_v2.chunk_id)
        got = repository._collection.get(ids=[record_id])
        assert got["documents"][0] == "갱신된 두 번째 버전 내용입니다."

    def test_same_case_id_multiple_chunks_stored_separately(self, repository):
        chunk1 = _case(chunk_id="CHUNK-001", content="첫 번째 청크")
        chunk2 = _case(chunk_id="CHUNK-002", content="두 번째 청크")

        repository.upsert_case_chunk(chunk1, [0.1, 0.2, 0.3, 0.4])
        repository.upsert_case_chunk(chunk2, [0.2, 0.3, 0.4, 0.5])

        assert repository.count() == 2


class TestSearch:
    def test_domain_filter_applied(self, repository):
        repository.upsert_case_chunk(_case(document_id="d1", domain="public_service"), [1.0, 0.0, 0.0, 0.0])
        repository.upsert_case_chunk(_case(document_id="d2", domain="finance"), [0.0, 1.0, 0.0, 0.0])

        hits = repository.search([1.0, 0.0, 0.0, 0.0], domain="finance", top_k=5)
        assert len(hits) == 1
        assert hits[0].metadata["domain"] == "finance"

    def test_no_domain_filter_returns_all(self, repository):
        repository.upsert_case_chunk(_case(document_id="d1", domain="public_service"), [1.0, 0.0, 0.0, 0.0])
        repository.upsert_case_chunk(_case(document_id="d2", domain="finance"), [0.0, 1.0, 0.0, 0.0])

        hits = repository.search([1.0, 0.0, 0.0, 0.0], top_k=5)
        assert len(hits) == 2

    def test_search_result_content_and_score_present(self, repository):
        case = _case()
        repository.upsert_case_chunk(case, [1.0, 0.0, 0.0, 0.0])

        hits = repository.search([1.0, 0.0, 0.0, 0.0], top_k=5)
        assert hits[0].content == case.content
        assert hits[0].score is not None
        assert hits[0].score > 0.9  # 동일 벡터이므로 cosine distance ~0, score ~1


class TestCollectionMismatch:
    def test_embedding_dimension_mismatch_raises(self, tmp_path):
        client = create_persistent_client(path=str(tmp_path / "chroma_data"))
        SimilarCaseRepository(
            client=client,
            collection_name=CASES_COLLECTION_DEFAULT,
            embedding_model="fake-case-embedder",
            embedding_dimension=4,
            embedding_version="embedding_v1",
        )
        with pytest.raises(SimilarCaseCollectionUnavailableError):
            SimilarCaseRepository(
                client=client,
                collection_name=CASES_COLLECTION_DEFAULT,
                embedding_model="fake-case-embedder",
                embedding_dimension=8,
                embedding_version="embedding_v1",
            )
