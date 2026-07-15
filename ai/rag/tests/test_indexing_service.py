"""
Unit Tests for ai.rag.retrieval.service.RAGIndexingService
(fake_kure_embedder + 실제 chromadb PersistentClient, KURE-v1 모델은 로딩하지 않음)
"""

from ai.rag.chunking.schemas import Chunk, ChunkingConfig, ChunkingResult, ChunkLocationType, ContentKind, SourceType
from ai.rag.domain import IndexingContext
from ai.rag.retrieval.chroma_store import ChromaVectorStore, create_persistent_client
from ai.rag.retrieval.service import RAGIndexingService

_COLLECTION = "project_documents_kure_v1"


def _make_chunking_result() -> ChunkingResult:
    chunks = [
        Chunk(
            chunk_id="chk_1",
            document_id="doc-1",
            content="접수기간은 2026년 3월 1일부터 3월 31일까지입니다.",
            chunk_index=0,
            content_kind=ContentKind.BODY,
            source_type=SourceType.URL_WEBPAGE,
            location_type=ChunkLocationType.WEB_SECTION,
            location_number=None,
            section_title="접수 안내",
            char_count=30,
            indexable=True,
        ),
        Chunk(
            chunk_id="chk_2",
            document_id="doc-1",
            content="목차\n1. 개요\n2. 접수방법",
            chunk_index=1,
            content_kind=ContentKind.TOC,
            source_type=SourceType.URL_WEBPAGE,
            location_type=ChunkLocationType.WEB_SECTION,
            location_number=None,
            section_title="목차",
            char_count=20,
            indexable=False,
        ),
    ]
    return ChunkingResult(document_id="doc-1", chunks=chunks, chunk_count=len(chunks), config=ChunkingConfig())


def _make_service(fake_kure_embedder, tmp_path) -> RAGIndexingService:
    client = create_persistent_client(path=str(tmp_path / "chroma_data"))
    store = ChromaVectorStore(
        client=client,
        collection_name=_COLLECTION,
        embedding_model=fake_kure_embedder.model_name,
        embedding_dimension=fake_kure_embedder.embedding_dimension,
        embedding_version="embedding_v1",
    )
    return RAGIndexingService(fake_kure_embedder, store)


class TestIndexChunkingResult:
    def test_full_flow_index_and_search(self, fake_kure_embedder, tmp_path):
        service = _make_service(fake_kure_embedder, tmp_path)
        context = IndexingContext(project_id="p1", document_id="doc-1", document_title="공모전 안내")

        indexing_result = service.index_chunking_result(_make_chunking_result(), context)
        assert indexing_result.embedded_count == 1  # TOC 청크(chk_2)는 indexable=False라 제외
        assert indexing_result.skipped_count == 1
        assert indexing_result.stored_record_count == 1

        results = service.search("접수기간이 언제인가요?", project_id="p1", top_k=3)
        assert len(results) == 1
        assert results[0].chunk_id == "chk_1"
        assert "접수기간" in results[0].content

    def test_chunk_count_and_stored_count_consistent(self, fake_kure_embedder, tmp_path):
        service = _make_service(fake_kure_embedder, tmp_path)
        context = IndexingContext(project_id="p1", document_id="doc-1")
        summary = service.index_chunking_result_with_summary(_make_chunking_result(), context)

        assert summary.chunk_count == 2
        assert summary.indexable_chunk_count == 1
        assert summary.stored_count == summary.embedding_count == 1

    def test_summary_excludes_vectors_and_embedding_text(self, fake_kure_embedder, tmp_path):
        service = _make_service(fake_kure_embedder, tmp_path)
        summary = service.index_chunking_result_with_summary(
            _make_chunking_result(), IndexingContext(project_id="p1", document_id="doc-1")
        )
        dumped = summary.model_dump()
        assert "embedding" not in dumped
        assert "embedding_text" not in dumped
        assert "embedded_chunks" not in dumped

    def test_reindex_after_removed_chunk_deletes_stale(self, fake_kure_embedder, tmp_path):
        service = _make_service(fake_kure_embedder, tmp_path)
        context = IndexingContext(project_id="p1", document_id="doc-1")
        service.index_chunking_result(_make_chunking_result(), context)

        smaller_result = ChunkingResult(
            document_id="doc-1",
            chunks=[],
            chunk_count=0,
            config=ChunkingConfig(),
        )
        result2 = service.index_chunking_result(smaller_result, context)
        assert result2.deleted_stale_count == 1
        assert result2.stored_record_count == 0
