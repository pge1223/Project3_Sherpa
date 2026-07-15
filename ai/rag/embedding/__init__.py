"""
Embedding Module
==================
ChunkingResult(indexable=True 청크)를 KURE-v1로 임베딩한다. Chroma 저장은
ai.rag.retrieval의 범위이며, 여기서는 임베딩까지만 다룬다.

사용 예시:
    from ai.rag.embedding import KUREEmbedder, EmbeddingConfig
    from ai.rag.domain import IndexingContext

    embedder = KUREEmbedder(EmbeddingConfig())
    context = IndexingContext(project_id="proj-1", document_id="doc-123")
    result = embedder.embed_chunking_result(chunking_result, context)
"""

from ai.rag.embedding.kure_embedder import KUREEmbedder, EmptyQueryError, NonFiniteEmbeddingError
from ai.rag.embedding.schemas import EmbeddingConfig, EmbeddedChunk, EmbeddingResult
from ai.rag.embedding.text_builder import build_embedding_text

__all__ = [
    "KUREEmbedder",
    "EmptyQueryError",
    "NonFiniteEmbeddingError",
    "EmbeddingConfig",
    "EmbeddedChunk",
    "EmbeddingResult",
    "build_embedding_text",
]
