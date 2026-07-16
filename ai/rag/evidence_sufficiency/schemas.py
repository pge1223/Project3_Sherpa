"""
Pydantic Schemas for Evidence Sufficiency (RAG-005)
========================================================
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class EvidenceSufficiencyStatus(str, Enum):
    """근거 충분도 상태. sufficient/partial/insufficient 3단계."""

    SUFFICIENT = "sufficient"
    PARTIAL = "partial"
    INSUFFICIENT = "insufficient"


class EvidenceReasonCode(str, Enum):
    """근거 부족/경고 사유를 나타내는 코드. 문자열을 코드 곳곳에 직접 쓰지 않기 위해 사용한다."""

    NO_RESULTS = "NO_RESULTS"
    NO_VALID_EVIDENCE = "NO_VALID_EVIDENCE"
    NO_QUALIFIED_EVIDENCE = "NO_QUALIFIED_EVIDENCE"
    BELOW_MIN_SCORE = "BELOW_MIN_SCORE"
    TOO_FEW_EVIDENCE = "TOO_FEW_EVIDENCE"
    DUPLICATE_EVIDENCE_ONLY = "DUPLICATE_EVIDENCE_ONLY"
    EMPTY_CONTENT = "EMPTY_CONTENT"
    MISSING_SOURCE_ID = "MISSING_SOURCE_ID"
    NO_LINKED_EVIDENCE = "NO_LINKED_EVIDENCE"

    # 경고성 코드 — 이 코드만으로 근거를 무효화하지는 않는다.
    MISSING_DOCUMENT_TITLE = "MISSING_DOCUMENT_TITLE"
    MISSING_LOCATION = "MISSING_LOCATION"
    SINGLE_SOURCE_ONLY = "SINGLE_SOURCE_ONLY"


class EvidenceSufficiencyResult(BaseModel):
    """근거 충분도 판정 결과. 회의 파이프라인에 그대로 직렬화해 전달할 수 있다."""

    status: EvidenceSufficiencyStatus

    is_sufficient: bool
    allow_definitive_judgment: bool
    allow_numeric_score: bool

    role_id: Optional[str] = None
    trace_id: Optional[str] = None

    total_evidence_count: int
    valid_evidence_count: int
    qualified_evidence_count: int
    duplicate_count: int = 0
    invalid_evidence_count: int = 0

    max_score: Optional[float] = None
    average_score: Optional[float] = None

    unique_document_count: int = 0
    unique_section_count: int = 0

    qualified_document_ids: list[str] = Field(default_factory=list)
    qualified_chunk_ids: list[str] = Field(default_factory=list)

    reason_codes: list[EvidenceReasonCode] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)

    prompt_guard: str


__all__ = [
    "EvidenceSufficiencyStatus",
    "EvidenceReasonCode",
    "EvidenceSufficiencyResult",
]
