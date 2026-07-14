"""
Document Chunking Module
==========================
ai.rag.parsers(DocumentExtractionResult)와 ai.rag.preprocessing(CleanedWebContent)의
결과를 받아 RAG 임베딩용 청크로 분할한다. LangGraph 없이 단독 실행/테스트 가능하며
임베딩·Chroma 저장은 이 모듈의 범위 밖이다.

사용 예시:
    from ai.rag.chunking import chunk_document, ChunkSourceContext, SourceType

    context = ChunkSourceContext(document_id="doc-123", source_type=SourceType.FILE_UPLOAD, file_type="pdf")
    result = chunk_document(extraction, context)
    for chunk in result.chunks:
        print(chunk.chunk_id, chunk.content_kind, chunk.location_type, chunk.location_number)
"""

from ai.rag.chunking.chunker import chunk_document
from ai.rag.chunking.schemas import (
    Chunk,
    ChunkingConfig,
    ChunkingResult,
    ChunkLocationType,
    ChunkSourceContext,
    ContentKind,
    SourceType,
)

__all__ = [
    "chunk_document",
    "Chunk",
    "ChunkingConfig",
    "ChunkingResult",
    "ChunkLocationType",
    "ChunkSourceContext",
    "ContentKind",
    "SourceType",
]
