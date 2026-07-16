"""
Similar Case Search (RAG-006)
===================================
현재 평가 문서와 유사한 공개 수상작·선정 사례·가이드 자료를 사례 전용 Chroma
컬렉션에서 검색한다. RAG-003(현재 프로젝트 업로드 문서 검색)과는 완전히 분리된
독립 모듈이며, LangGraph나 ai.meeting.graph에 의존하지 않는다.

유사 사례는 항상 참고 자료(reference_only=True)이며 현재 문서의 직접 평가 근거가
아니다. 자세한 내용은 README.md 참고.
"""

from ai.rag.similar_cases.comparison_service import CaseAggregate, ComparisonOutcome, LLMCall, SupportingChunk
from ai.rag.similar_cases.config import SimilarCaseConfig
from ai.rag.similar_cases.exceptions import (
    SimilarCaseCollectionUnavailableError,
    SimilarCaseComparisonError,
    SimilarCaseError,
    SimilarCaseIndexingError,
    SimilarCaseSearchError,
    SimilarCaseValidationError,
)
from ai.rag.similar_cases.indexing_service import (
    EmbedderLike,
    SimilarCaseIndexingService,
    SimilarCaseIndexingSummary,
)
from ai.rag.similar_cases.repository import CaseChunkHit, SimilarCaseRepository, build_case_record_id
from ai.rag.similar_cases.schemas import (
    ComparisonMode,
    SimilarCaseDocument,
    SimilarCaseEvidence,
    SimilarCaseResult,
    SimilarCaseSearchRequest,
    SimilarCaseSearchResponse,
    SimilarCaseType,
)
from ai.rag.similar_cases.search_service import SimilarCaseSearchService, build_similar_case_query

__all__ = [
    "SimilarCaseConfig",
    "SimilarCaseError",
    "SimilarCaseValidationError",
    "SimilarCaseCollectionUnavailableError",
    "SimilarCaseIndexingError",
    "SimilarCaseSearchError",
    "SimilarCaseComparisonError",
    "SimilarCaseType",
    "ComparisonMode",
    "SimilarCaseDocument",
    "SimilarCaseSearchRequest",
    "SimilarCaseEvidence",
    "SimilarCaseResult",
    "SimilarCaseSearchResponse",
    "SimilarCaseRepository",
    "CaseChunkHit",
    "build_case_record_id",
    "EmbedderLike",
    "SimilarCaseIndexingService",
    "SimilarCaseIndexingSummary",
    "SimilarCaseSearchService",
    "build_similar_case_query",
    "CaseAggregate",
    "SupportingChunk",
    "ComparisonOutcome",
    "LLMCall",
]
