"""
Notice Criteria Extraction (공고문 평가기준 추출)
=====================================================
공고문 파싱·청킹 결과(ai.rag.chunking.chunk_document() 출력)에서 평가기준(심사기준)을
찾아 contracts/mocks/notice_criteria_*.json과 동일한 구조로 반환한다.

범위가 아닌 것: domain 자동 분류(도메인은 호출자가 입력으로 넘김), persona 매칭,
rubric_mapping 생성 — 이 모듈의 출력이 그 다음 단계들의 입력 후보가 될 뿐이다.
"""

from ai.rag.criteria_extraction.schemas import (
    CriteriaExtractionRequest,
    Criterion,
    ExtractionStatus,
    NoticeCriteriaMeta,
    NoticeCriteriaResult,
)
from ai.rag.criteria_extraction.selection import select_candidate_chunks
from ai.rag.criteria_extraction.service import (
    CriteriaExtractionError,
    CriteriaExtractionService,
    LLMCall,
)

__all__ = [
    "CriteriaExtractionRequest",
    "Criterion",
    "ExtractionStatus",
    "NoticeCriteriaMeta",
    "NoticeCriteriaResult",
    "select_candidate_chunks",
    "CriteriaExtractionError",
    "CriteriaExtractionService",
    "LLMCall",
]
