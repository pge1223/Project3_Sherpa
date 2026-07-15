"""
Evidence Linking Configuration Defaults
===========================================
평가 의견과 검색 결과를 연결할 때 근거 채택 기준/인용문 길이를 관리한다.
"""

from pydantic import BaseModel

# 이 점수 미만인 검색 결과는 근거로 채택하지 않는다 (RAG-002 score, RAG-003 final_score 모두
# cosine 기반 [-1, 1] 스케일이며, 실제 정답 매칭은 대체로 0.3 이상에서 관측됨).
DEFAULT_MIN_EVIDENCE_SCORE: float = 0.3

# 평가 의견 1건에 연결할 최대 근거 개수
DEFAULT_MAX_EVIDENCE: int = 3

# quote 최종 최대 길이 (초과 시 말줄임표로 절단)
DEFAULT_QUOTE_MAX_LENGTH: int = 300

# 관련 문장을 찾지 못했을 때 청크 앞부분에서 가져올 길이
DEFAULT_QUOTE_CONTEXT_LENGTH: int = 80

# 의견과 청크(본문 또는 section_title)가 관련 있다고 인정하기 위한 최소 키워드 겹침 수
DEFAULT_MIN_KEYWORD_OVERLAP: int = 1

# calculate_relevance_score() 보조 지표를 관련성 인정 기준으로 쓸 때의 최소값
DEFAULT_MIN_RELEVANCE_SCORE: float = 0.1

# True면 검색 점수가 충분해도 의견과 무관한 청크는 근거 후보에서 제외한다
DEFAULT_REQUIRE_TEXT_RELEVANCE: bool = True


class EvidenceLinkingConfig(BaseModel):
    """근거 채택 기준과 인용문 길이 설정. 서비스 생성 시 주입해 튜닝할 수 있다."""

    min_evidence_score: float = DEFAULT_MIN_EVIDENCE_SCORE
    max_evidence: int = DEFAULT_MAX_EVIDENCE
    quote_max_length: int = DEFAULT_QUOTE_MAX_LENGTH
    quote_context_length: int = DEFAULT_QUOTE_CONTEXT_LENGTH
    min_keyword_overlap: int = DEFAULT_MIN_KEYWORD_OVERLAP
    min_relevance_score: float = DEFAULT_MIN_RELEVANCE_SCORE
    require_text_relevance: bool = DEFAULT_REQUIRE_TEXT_RELEVANCE


__all__ = [
    "EvidenceLinkingConfig",
    "DEFAULT_MIN_EVIDENCE_SCORE",
    "DEFAULT_MAX_EVIDENCE",
    "DEFAULT_QUOTE_MAX_LENGTH",
    "DEFAULT_QUOTE_CONTEXT_LENGTH",
    "DEFAULT_MIN_KEYWORD_OVERLAP",
    "DEFAULT_MIN_RELEVANCE_SCORE",
    "DEFAULT_REQUIRE_TEXT_RELEVANCE",
]
