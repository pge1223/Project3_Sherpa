"""
RAG Indexing Service (Integration Layer)
===========================================
백엔드가 KUREEmbedder/ChromaVectorStore를 직접 조립하지 않아도 되도록 묶어주는
단일 진입점. LangGraph/FastAPI/MongoDB와 무관하게 단독 호출 가능하다.
"""

from typing import Optional

from ai.rag.chunking.schemas import ChunkingResult
from ai.rag.domain.schemas import IndexingContext
from ai.rag.embedding.kure_embedder import KUREEmbedder
from ai.rag.retrieval.chroma_store import ChromaVectorStore
from ai.rag.retrieval.schemas import IndexingResult, IndexingSummary, SearchResult


class RAGIndexingService:
    def __init__(self, embedder: KUREEmbedder, vector_store: ChromaVectorStore):
        self._embedder = embedder
        self._vector_store = vector_store

    def index_chunking_result(
        self,
        chunking_result: ChunkingResult,
        context: IndexingContext,
    ) -> IndexingResult:
        """ChunkingResult -> 임베딩 -> Chroma upsert -> stale record 삭제 -> IndexingResult."""
        embedding_result = self._embedder.embed_chunking_result(chunking_result, context)
        return self._vector_store.upsert_embedding_result(embedding_result, context)

    def index_chunking_result_with_summary(
        self,
        chunking_result: ChunkingResult,
        context: IndexingContext,
    ) -> IndexingSummary:
        """index_chunking_result()와 동일하게 색인하되, 벡터/embedding_text를 뺀
        프런트엔드 전달용 요약(IndexingSummary)을 반환한다."""
        indexable_chunk_count = sum(1 for c in chunking_result.chunks if c.indexable)
        indexing_result = self.index_chunking_result(chunking_result, context)
        return IndexingSummary(
            project_id=indexing_result.project_id,
            document_id=indexing_result.document_id,
            status=indexing_result.status,
            chunk_count=chunking_result.chunk_count,
            indexable_chunk_count=indexable_chunk_count,
            embedding_count=indexing_result.embedded_count,
            stored_count=indexing_result.stored_record_count,
            skipped_count=indexing_result.skipped_count,
            failed_count=indexing_result.failed_count,
            embedding_model=self._embedder.model_name,
            embedding_dimension=self._embedder.embedding_dimension,
            collection_name=indexing_result.collection_name,
            warnings=indexing_result.warnings,
        )

    def search(
        self,
        query: str,
        project_id: str,
        document_id: Optional[str] = None,
        top_k: int = 5,
    ) -> list[SearchResult]:
        """질문 문자열 -> KURE-v1 query 임베딩 -> project_id 필터 검색 -> SearchResult."""
        query_embedding = self._embedder.embed_query(query)
        return self._vector_store.search(
            query_embedding=query_embedding,
            project_id=project_id,
            document_id=document_id,
            top_k=top_k,
        )

    def delete_project(self, project_id: str) -> int:
        """project_id 기준으로 프로젝트 전체 벡터 청크를 삭제한다. ChromaVectorStore.delete_project()를
        그대로 호출하고 삭제된 건수를 그대로 반환한다(PRJ-004 프로젝트 삭제 연동, backend는
        run_in_threadpool로 감싸 호출한다 — 이 메서드 자체는 동기다)."""
        return self._vector_store.delete_project(project_id)
