"""
Pydantic Schemas for Similar Case Search (RAG-006)
========================================================
"""

import math
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from ai.rag.similar_cases.config import DEFAULT_MAX_TOP_K
from ai.rag.similar_cases.exceptions import SimilarCaseValidationError


class SimilarCaseType(str, Enum):
    """사례 유형. REJECTED_CASE는 실제 탈락 사례 데이터가 있을 때만 사용한다 —
    데이터가 없다고 임의로 REJECTED_CASE를 만들어내지 않는다."""

    AWARD_WINNER = "award_winner"
    SELECTED_CASE = "selected_case"
    GUIDE = "guide"
    REJECTED_CASE = "rejected_case"


class ComparisonMode(str, Enum):
    """검색 결과에 실제 탈락 사례가 포함됐는지를 나타낸다."""

    SELECTED_CASE_GAP = "selected_case_gap"
    SELECTED_AND_REJECTED_CASES = "selected_and_rejected_cases"


def _require_non_blank(value: str, field_name: str) -> str:
    if not value or not value.strip():
        raise SimilarCaseValidationError(f"{field_name}는 빈 문자열일 수 없습니다")
    return value


class SimilarCaseDocument(BaseModel):
    """색인 대상 사례 청크 1건. 공개 출처가 없는 사례는 색인하지 않는다(출처 필드 필수)."""

    case_id: str
    title: str
    case_type: SimilarCaseType

    domain: str
    evaluation_criteria: list[str] = Field(default_factory=list)

    source_name: str
    source_url: str

    document_id: str
    chunk_id: str
    content: str

    page: Optional[int] = None
    section: Optional[str] = None
    published_at: Optional[str] = None

    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "case_id", "title", "domain", "source_name", "source_url", "document_id", "chunk_id", "content"
    )
    @classmethod
    def _not_blank(cls, v: str, info) -> str:
        return _require_non_blank(v, info.field_name)

    @field_validator("evaluation_criteria")
    @classmethod
    def _criteria_entries_not_blank(cls, v: list[str]) -> list[str]:
        for item in v:
            if not item or not item.strip():
                raise SimilarCaseValidationError("evaluation_criteria 항목은 빈 문자열일 수 없습니다")
        return v


class SimilarCaseSearchRequest(BaseModel):
    """SimilarCaseSearchService.search()의 입력."""

    document_summary: str
    domain: str
    evaluation_criteria: list[str]

    top_k: int = 5
    min_score: Optional[float] = None

    current_document_id: Optional[str] = None
    trace_id: Optional[str] = None

    @field_validator("document_summary", "domain")
    @classmethod
    def _not_blank(cls, v: str, info) -> str:
        return _require_non_blank(v, info.field_name)

    @field_validator("evaluation_criteria")
    @classmethod
    def _criteria_not_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise SimilarCaseValidationError("evaluation_criteria는 비어 있을 수 없습니다")
        for item in v:
            if not item or not item.strip():
                raise SimilarCaseValidationError("evaluation_criteria 항목은 빈 문자열일 수 없습니다")
        return v

    @field_validator("top_k")
    @classmethod
    def _top_k_positive(cls, v: int) -> int:
        if v <= 0:
            raise SimilarCaseValidationError("top_k는 1 이상이어야 합니다")
        if v > DEFAULT_MAX_TOP_K:
            raise SimilarCaseValidationError(f"top_k는 {DEFAULT_MAX_TOP_K}를 초과할 수 없습니다")
        return v

    @field_validator("min_score")
    @classmethod
    def _min_score_finite(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return v
        if math.isnan(v) or math.isinf(v):
            raise SimilarCaseValidationError("min_score는 NaN 또는 무한대일 수 없습니다")
        return v


class SimilarCaseEvidence(BaseModel):
    """사례 결과 1건을 뒷받침하는 원문 근거(청크) 1개."""

    document_id: str
    chunk_id: str

    page: Optional[int] = None
    section: Optional[str] = None
    quote: str

    similarity_score: float


class SimilarCaseResult(BaseModel):
    """유사 사례 검색 결과 1건 (사례 단위로 집계됨)."""

    case_id: str
    title: str
    case_type: SimilarCaseType

    domain: str
    source_name: str
    source_url: str

    similarity_score: float

    matched_criteria: list[str] = Field(default_factory=list)
    similarity_reasons: list[str] = Field(default_factory=list)

    common_points: list[str] = Field(default_factory=list)
    different_points: list[str] = Field(default_factory=list)
    current_document_gaps: list[str] = Field(default_factory=list)

    evidence: list[SimilarCaseEvidence] = Field(default_factory=list)

    # 유사 사례는 항상 참고 자료이며 현재 문서의 직접 평가 근거가 아니다 (RAG-005 근거
    # 충족도 판정이나 숫자 점수 허용 정책과 무관함). 회의 파이프라인이 이 필드를 보고
    # 실수로 점수 근거로 사용하지 않도록 명시적으로 True를 내려준다.
    reference_only: bool = True


class SimilarCaseSearchResponse(BaseModel):
    """SimilarCaseSearchService.search()의 반환값."""

    results: list[SimilarCaseResult] = Field(default_factory=list)

    total_results: int = 0
    has_rejected_cases: bool = False
    comparison_mode: ComparisonMode = ComparisonMode.SELECTED_CASE_GAP

    query_text: str
    trace_id: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)

    reference_only: bool = True

    @model_validator(mode="after")
    def _total_results_matches(self) -> "SimilarCaseSearchResponse":
        if self.total_results != len(self.results):
            self.total_results = len(self.results)
        return self


__all__ = [
    "SimilarCaseType",
    "ComparisonMode",
    "SimilarCaseDocument",
    "SimilarCaseSearchRequest",
    "SimilarCaseEvidence",
    "SimilarCaseResult",
    "SimilarCaseSearchResponse",
]
