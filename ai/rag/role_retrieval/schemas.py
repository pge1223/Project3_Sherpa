"""
Pydantic Schemas for Role-Aware Retrieval
=============================================
"""

from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from ai.rag.role_retrieval.config import DEFAULT_CANDIDATE_K_MULTIPLIER


class RoleProfile(BaseModel):
    """심사위원 역할 1개를 정의하는 프로필. roles.py의 레지스트리에서 관리된다."""

    role_id: str
    display_name: str
    description: str
    query_instruction: str = Field(..., description="검색 질의 생성 시 사용자 질문 앞에 붙는 역할 지침 문장")
    focus_keywords: list[str] = Field(default_factory=list, description="content/문서 제목에서 역할 관련도를 판단하는 키워드")
    section_keywords: list[str] = Field(default_factory=list, description="section_title에서 역할 관련도를 판단하는 키워드")


class RoleSearchRequest(BaseModel):
    """RoleAwareRetrievalService.search_by_role() 입력 검증용 내부 요청 스키마."""

    query: str
    role_id: Optional[str] = None
    project_id: str
    document_id: Optional[str] = None
    top_k: int = 5
    candidate_k: Optional[int] = None

    @field_validator("query", "project_id")
    @classmethod
    def _must_not_be_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("빈 문자열일 수 없습니다")
        return v

    @field_validator("top_k")
    @classmethod
    def _top_k_must_be_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("top_k는 1 이상이어야 합니다")
        return v

    @model_validator(mode="after")
    def _resolve_candidate_k(self) -> "RoleSearchRequest":
        if self.candidate_k is None:
            self.candidate_k = self.top_k * DEFAULT_CANDIDATE_K_MULTIPLIER
        elif self.candidate_k < self.top_k:
            raise ValueError("candidate_k는 top_k 이상이어야 합니다")
        return self


class RoleSearchResult(BaseModel):
    """역할 관련도가 반영된 검색 결과 1건. 임베딩 벡터는 포함하지 않는다."""

    record_id: str
    chunk_id: str
    document_id: str
    content: str
    distance: Optional[float] = None
    semantic_score: Optional[float] = None
    role_score: float
    final_score: float
    role_id: Optional[str] = None
    metadata: dict = Field(default_factory=dict)


class RoleSearchResponse(BaseModel):
    """RoleAwareRetrievalService.search_by_role()의 최종 반환 스키마."""

    query: str
    expanded_query: str
    role_id: Optional[str] = None
    role_name: Optional[str] = None
    project_id: str
    document_id: Optional[str] = None
    results: list[RoleSearchResult] = Field(default_factory=list)
    result_count: int
    warnings: list[str] = Field(default_factory=list)
