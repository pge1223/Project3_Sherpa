"""
Unit Tests for ai.rag.similar_cases.indexing_service
"""

import pytest
from pydantic import ValidationError

from ai.rag.retrieval.chroma_store import create_persistent_client
from ai.rag.similar_cases.config import DEFAULT_COLLECTION_NAME
from ai.rag.similar_cases.exceptions import SimilarCaseIndexingError, SimilarCaseValidationError
from ai.rag.similar_cases.indexing_service import SimilarCaseIndexingService
from ai.rag.similar_cases.repository import SimilarCaseRepository
from ai.rag.similar_cases.schemas import SimilarCaseDocument, SimilarCaseType
from ai.rag.tests._similar_case_fixtures import FakeCaseEmbedder

_DIM = 4


def _case(case_id="CASE-001", document_id="DOC-001", chunk_id="CHUNK-001", **overrides) -> SimilarCaseDocument:
    base = dict(
        case_id=case_id,
        title="공공데이터 활용 공모전 수상작",
        case_type=SimilarCaseType.AWARD_WINNER,
        domain="public_service",
        evaluation_criteria=["문제 정의", "기술성"],
        source_name="공모전 공식 홈페이지",
        source_url="https://example.org/award/001",
        document_id=document_id,
        chunk_id=chunk_id,
        content="본 서비스는 공공데이터를 활용해 문서를 자동 평가합니다.",
    )
    base.update(overrides)
    return SimilarCaseDocument(**base)


@pytest.fixture
def repository(tmp_path):
    client = create_persistent_client(path=str(tmp_path / "chroma_data"))
    return SimilarCaseRepository(
        client=client,
        collection_name=DEFAULT_COLLECTION_NAME,
        embedding_model="fake-case-embedder",
        embedding_dimension=_DIM,
        embedding_version="embedding_v1",
    )


@pytest.fixture
def embedder():
    return FakeCaseEmbedder(dimension=_DIM)


class TestIndexCases:
    def test_indexes_into_case_collection(self, repository, embedder):
        service = SimilarCaseIndexingService(repository, embedder)
        summary = service.index_cases([_case()])

        assert summary.indexed_count == 1
        assert summary.collection_name == DEFAULT_COLLECTION_NAME
        assert repository.count() == 1

    def test_project_documents_collection_untouched(self, tmp_path, repository, embedder):
        from ai.rag.domain.config import DEFAULT_COLLECTION_NAME as PROJECT_DOCS_COLLECTION

        client = repository._client
        # 사례 색인 전, 프로젝트 문서 컬렉션은 아직 생성되지 않았어야 한다.
        assert PROJECT_DOCS_COLLECTION not in [c.name for c in client.list_collections()]

        service = SimilarCaseIndexingService(repository, embedder)
        service.index_cases([_case()])

        collection_names = [c.name for c in client.list_collections()]
        assert DEFAULT_COLLECTION_NAME in collection_names
        assert PROJECT_DOCS_COLLECTION not in collection_names

    def test_blank_content_skipped_with_warning(self, repository, embedder):
        """공백만 있는 content는 이미 SimilarCaseDocument 생성 시점에 SimilarCaseValidationError로
        거부되므로(스키마 테스트 참고), 여기서는 pydantic validation을 우회한 legacy 데이터가
        섞여 들어온 경우에도 index_cases()가 방어적으로 건너뛰는지 확인한다."""
        service = SimilarCaseIndexingService(repository, embedder)
        blank_case = SimilarCaseDocument.model_construct(**{**_case().model_dump(), "content": "   "})

        summary = service.index_cases([blank_case])

        assert summary.indexed_count == 0
        assert summary.skipped_count == 1
        assert any("content가 비어" in w for w in summary.warnings)

    def test_partial_batch_failure_does_not_abort_others(self, repository, embedder):
        service = SimilarCaseIndexingService(repository, embedder)
        valid_case = _case(chunk_id="CHUNK-001", content="유효한 첫 번째 사례")
        blank_case = SimilarCaseDocument.model_construct(
            **{**_case(chunk_id="CHUNK-002").model_dump(), "content": ""}
        )
        summary = service.index_cases([valid_case, blank_case])

        assert summary.indexed_count == 1
        assert summary.skipped_count == 1
        assert repository.count() == 1

    def test_reindexing_same_chunk_does_not_duplicate(self, repository, embedder):
        service = SimilarCaseIndexingService(repository, embedder)
        service.index_cases([_case()])
        service.index_cases([_case(content="갱신된 내용입니다.")])

        assert repository.count() == 1

    def test_multiple_chunks_of_same_case_all_indexed(self, repository, embedder):
        service = SimilarCaseIndexingService(repository, embedder)
        cases = [
            _case(chunk_id="CHUNK-001", content="첫 번째 청크"),
            _case(chunk_id="CHUNK-002", content="두 번째 청크"),
        ]
        summary = service.index_cases(cases)

        assert summary.indexed_count == 2
        assert repository.count() == 2

    def test_total_input_count_reported(self, repository, embedder):
        service = SimilarCaseIndexingService(repository, embedder)
        blank_case = SimilarCaseDocument.model_construct(
            **{**_case(chunk_id="CHUNK-002").model_dump(), "content": ""}
        )
        summary = service.index_cases([_case(chunk_id="CHUNK-001"), blank_case])
        assert summary.total_input_count == 2

    def test_indexing_error_wraps_unexpected_exception(self, repository, embedder):
        class _BrokenRepository:
            _collection_name = DEFAULT_COLLECTION_NAME
            collection_name = DEFAULT_COLLECTION_NAME

            def upsert_case_chunk(self, case, embedding):
                raise RuntimeError("chroma 연결 끊김")

        service = SimilarCaseIndexingService(_BrokenRepository(), embedder)
        with pytest.raises(SimilarCaseIndexingError):
            service.index_cases([_case()])


class TestMissingSourceRejectedAtSchemaLevel:
    def test_blank_source_url_rejected(self):
        with pytest.raises(SimilarCaseValidationError):
            _case(source_url="")

    def test_blank_source_name_rejected(self):
        with pytest.raises(SimilarCaseValidationError):
            _case(source_name="")

    def test_blank_case_id_rejected(self):
        with pytest.raises(SimilarCaseValidationError):
            _case(case_id="")

    def test_blank_content_rejected_at_construction(self):
        # 빈 문자열이나 공백만 있는 content는 SimilarCaseDocument 생성 시점에 이미
        # 거부된다 — index_cases()의 스킵 로직은 pydantic 검증을 우회한 legacy 데이터에
        # 대한 방어선일 뿐이다(위 test_blank_content_skipped_with_warning 참고).
        with pytest.raises(SimilarCaseValidationError):
            _case(content="   ")
