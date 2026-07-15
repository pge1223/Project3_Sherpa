"""
Retrieval Module (Chroma Vector Store + Indexing Service)
=============================================================
EmbeddingResult를 Chroma에 저장/삭제/검색하고, KUREEmbedder와 묶은 통합
RAGIndexingService를 제공한다. LangGraph/FastAPI/MongoDB와 무관하게 단독 실행 가능하다.

사용 예시:
    from ai.rag.embedding import KUREEmbedder
    from ai.rag.retrieval import ChromaVectorStore, RAGIndexingService, create_persistent_client
    from ai.rag.domain import IndexingContext

    embedder = KUREEmbedder()
    client = create_persistent_client(path="./chroma_data")
    store = ChromaVectorStore(
        client=client,
        collection_name="project_documents_kure_v1",
        embedding_model=embedder.model_name,
        embedding_dimension=embedder.embedding_dimension,
        embedding_version="embedding_v1",
    )
    service = RAGIndexingService(embedder, store)

    context = IndexingContext(project_id="proj-1", document_id="doc-123")
    service.index_chunking_result(chunking_result, context)
    service.search("접수기간은 언제인가요?", project_id="proj-1")
"""

from ai.rag.retrieval.chroma_store import ChromaVectorStore, build_record_id, create_persistent_client
from ai.rag.retrieval.service import RAGIndexingService
from ai.rag.retrieval.schemas import IndexingResult, IndexingSummary, IndexingStatus, SearchResult
from ai.rag.retrieval.metadata import sanitize_metadata_for_chroma, restore_metadata

__all__ = [
    "ChromaVectorStore",
    "RAGIndexingService",
    "build_record_id",
    "create_persistent_client",
    "IndexingResult",
    "IndexingSummary",
    "IndexingStatus",
    "SearchResult",
    "sanitize_metadata_for_chroma",
    "restore_metadata",
]
