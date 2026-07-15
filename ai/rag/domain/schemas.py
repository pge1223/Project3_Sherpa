"""
Shared Domain Schemas
======================
embedding/과 retrieval/ 양쪽에서 공통으로 쓰는 컨텍스트만 정의한다.
"""

import re
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from ai.rag.chunking.schemas import ChunkingResult
from ai.rag.domain.config import COLLECTION_NAME_PATTERN, DEFAULT_COLLECTION_NAME

_COLLECTION_NAME_RE = re.compile(COLLECTION_NAME_PATTERN)


class IndexingContext(BaseModel):
    """색인 호출자가 넘겨주는 컨텍스트. project_id는 프로젝트 간 데이터 격리를 위해 필수다."""

    project_id: str = Field(..., description="프로젝트 격리 기준 ID (필수)")
    document_id: str = Field(..., description="ChunkingResult.document_id와 반드시 일치해야 함")
    document_title: Optional[str] = Field(
        None, description="ChunkSourceContext.document_title과 동일한 값을 호출자가 그대로 전달 (Chunk엔 저장되지 않음)"
    )
    collection_name: str = Field(default=DEFAULT_COLLECTION_NAME, description="Chroma 컬렉션 이름")

    @field_validator("project_id", "document_id")
    @classmethod
    def _must_not_be_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("빈 문자열일 수 없습니다")
        return v

    @field_validator("collection_name")
    @classmethod
    def _validate_collection_name(cls, v: str) -> str:
        if not _COLLECTION_NAME_RE.match(v):
            raise ValueError(
                f"Chroma 컬렉션 이름 규칙을 만족하지 않습니다 (3~512자, [a-zA-Z0-9._-], 시작/끝은 영숫자): {v!r}"
            )
        return v

    def ensure_matches(self, chunking_result: ChunkingResult) -> None:
        """IndexingContext.document_id와 ChunkingResult.document_id가 다르면 오류."""
        if self.document_id != chunking_result.document_id:
            raise ValueError(
                f"IndexingContext.document_id('{self.document_id}')와 "
                f"ChunkingResult.document_id('{chunking_result.document_id}')가 다릅니다"
            )


class CollectionConfigMismatchError(ValueError):
    """기존 Chroma 컬렉션의 임베딩 모델/차원/버전이 현재 설정과 다를 때 발생"""


class InvalidTopKError(ValueError):
    """top_k가 1 미만일 때 발생"""
