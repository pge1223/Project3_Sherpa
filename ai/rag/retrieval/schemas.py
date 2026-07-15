"""
Pydantic Schemas for Chroma Vector Store / Indexing
======================================================
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class IndexingStatus(str, Enum):
    SUCCESS = "success"       # 저장 대상이 1개 이상이고 전부 성공
    PARTIAL = "partial"       # 일부 청크만 임베딩/저장 성공 (failed_count > 0)
    EMPTY = "empty"           # 저장 대상이 0개 (오류 아님, 경고로만 처리)
    FAILED = "failed"         # 임베딩/저장 자체가 전부 실패


class SearchResult(BaseModel):
    """Top-K 유사도 검색 결과 1건"""

    record_id: str = Field(..., description="Chroma record ID (project_id::chunk_id 형태, 내부용)")
    chunk_id: str
    document_id: str
    content: str
    distance: Optional[float] = Field(None, description="Chroma가 반환한 원본 거리값 (cosine distance)")
    score: Optional[float] = Field(
        None, description="1.0 - distance (cosine distance 정의가 이와 일치한다고 확인된 경우에만 계산)"
    )
    metadata: dict = Field(default_factory=dict, description="복원된 출처 메타데이터 (JSON 문자열로 저장된 리스트 필드 포함 복원됨)")


class IndexingResult(BaseModel):
    """RAGIndexingService.index_chunking_result() / ChromaVectorStore.upsert_embedding_result()의 반환 스키마"""

    project_id: str
    document_id: str
    collection_name: str
    embedded_count: int = Field(0, description="임베딩에 성공한 청크 수")
    upserted_count: int = Field(0, description="Chroma에 upsert된 레코드 수")
    deleted_stale_count: int = Field(0, description="재색인 시 삭제된 stale record 수")
    skipped_count: int = Field(0, description="indexable=False라서 건너뛴 청크 수")
    failed_count: int = Field(0, description="임베딩 실패한 청크 수")
    stored_record_count: int = Field(0, description="처리 완료 후 이 project_id+document_id로 Chroma에 남아있는 레코드 수")
    warnings: list[str] = Field(default_factory=list)
    status: IndexingStatus


class IndexingSummary(BaseModel):
    """프런트엔드/백엔드에 전달할 요약. 임베딩 벡터와 embedding_text는 포함하지 않는다."""

    project_id: str
    document_id: str
    status: IndexingStatus
    chunk_count: int
    indexable_chunk_count: int
    embedding_count: int
    stored_count: int
    skipped_count: int
    failed_count: int
    embedding_model: str
    embedding_dimension: int
    collection_name: str
    warnings: list[str] = Field(default_factory=list)
