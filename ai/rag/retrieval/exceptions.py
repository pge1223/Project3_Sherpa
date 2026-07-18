"""
RAG Indexing Pipeline Exceptions
===================================
RAGIndexingService.index_chunking_result()가 임베딩 단계와 Chroma 저장 단계에서
실패를 구분해 던지기 위한 예외 계층. backend(documents.py 등 호출부)가 "어느 단계에서
실패했는지"를 isinstance()로 구분할 수 있게 하는 것이 목적이다 — 색인 실패 자체를
막지는 않는다(호출부는 여전히 try/except로 감싸 status=indexing_failed 등으로 처리).

2026-07-18, fetch-url 색인 5분+ hang 조사(용준/Claude) 중 도입: hang 자체는 예외가
아니라 블로킹이라 이 계층만으로는 못 잡지만, 실패가 "임베딩 중"인지 "Chroma 저장 중"인지
구분 가능해지면 재발 시 원인 좁히기가 훨씬 쉬워진다.
"""


class RAGIndexingError(Exception):
    """RAG 색인 파이프라인(임베딩/Chroma 저장) 공통 최상위 예외.

    stage: 실패한 단계 식별자(예: "embed", "chroma_upsert")
    document_id: 실패한 문서 ID (원인 추적용)
    원본 예외는 __cause__(raise ... from exc)로 그대로 보존한다.
    """

    def __init__(self, stage: str, document_id: str, message: str):
        self.stage = stage
        self.document_id = document_id
        super().__init__(f"[{stage}] document_id={document_id}: {message}")


class EmbeddingStageError(RAGIndexingError):
    """KUREEmbedder.embed_chunking_result() 단계에서 실패했을 때 발생."""


class VectorStoreStageError(RAGIndexingError):
    """ChromaVectorStore.upsert_embedding_result() (Chroma 저장) 단계에서 실패했을 때 발생."""
