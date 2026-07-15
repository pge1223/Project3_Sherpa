"""
Pydantic Schemas for Evidence Linking
=========================================
"""

from typing import Optional

from pydantic import BaseModel, Field


class EvidenceSource(BaseModel):
    """평가 의견 1건을 뒷받침하는 원문 근거 1개."""

    document_id: str
    chunk_id: str

    document_title: Optional[str] = None
    page_number: Optional[int] = None
    section_title: Optional[str] = None
    content_kind: Optional[str] = None

    quote: str = Field(..., description="원본 content에서 그대로 추출된 인용문 (LLM으로 새로 생성하지 않음)")
    semantic_score: Optional[float] = None
    role_score: Optional[float] = None
    final_score: Optional[float] = None


class LinkedEvaluation(BaseModel):
    """평가 의견 + 근거 출처 목록. 근거가 없으면 has_evidence=False, evidence=[]."""

    opinion: str
    role_id: Optional[str] = None
    role_name: Optional[str] = None

    has_evidence: bool
    evidence: list[EvidenceSource] = Field(default_factory=list)
