"""
Rule-Based Relevance Filtering
===================================
검색 점수가 높아도 평가 의견과 무관한 청크가 근거로 선택되지 않도록,
후보 선택 단계에서 의견과 청크(본문/섹션 제목/역할 키워드)의 관련성을 검사한다.
LLM 호출 없음 — 키워드 겹침만으로 판단한다.
"""

import re
from typing import Optional

from ai.rag.evidence_linking.config import EvidenceLinkingConfig

_TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9]+")

# 평가 의견/청크에서 흔히 등장하지만 관련성 판단에는 도움이 되지 않는 일반 단어.
STOPWORDS: frozenset[str] = frozenset({
    "부족합니다", "필요합니다", "평가", "내용", "관련", "대한", "위한",
    "있습니다", "합니다", "문서", "사업",
})


def _is_stopword(token: str) -> bool:
    for stopword in STOPWORDS:
        if token == stopword:
            return True
        # "사업의", "사업을"처럼 조사 한 글자만 붙은 형태도 같은 불용어로 취급한다.
        if token.startswith(stopword) and len(token) - len(stopword) <= 1:
            return True
    return False


def extract_keywords(text: Optional[str]) -> set[str]:
    """text에서 불용어와 1글자 토큰을 제외한 핵심 키워드를 뽑는다."""
    if not text:
        return set()
    tokens = _TOKEN_RE.findall(text)
    return {token for token in tokens if len(token) >= 2 and not _is_stopword(token)}


def _stem(token: str) -> str:
    """조사 등 접미사 영향을 줄이기 위해 2글자 이하로 축약한 어간."""
    return token if len(token) <= 2 else token[:2]


def _stem_overlap_count(keywords: set[str], target_text: Optional[str]) -> int:
    if not keywords or not target_text:
        return 0
    return sum(1 for keyword in keywords if _stem(keyword) in target_text)


def calculate_relevance_score(
    opinion: str,
    content: str,
    section_title: Optional[str] = None,
    document_title: Optional[str] = None,
    role_keywords: Optional[list[str]] = None,
) -> float:
    """의견과 청크 사이의 관련성을 0~1 사이 근사치로 계산한다 (보조 지표)."""
    opinion_keywords = extract_keywords(opinion)
    if not opinion_keywords:
        return 0.0

    content_overlap = _stem_overlap_count(opinion_keywords, content)
    section_overlap = _stem_overlap_count(opinion_keywords, section_title)
    document_overlap = _stem_overlap_count(opinion_keywords, document_title)

    role_hits = 0
    if role_keywords and content:
        role_hits = sum(1 for keyword in role_keywords if keyword and keyword in content)

    weighted = content_overlap * 2 + section_overlap * 1.5 + document_overlap + role_hits
    denominator = len(opinion_keywords) * 2
    return min(weighted / denominator, 1.0) if denominator else 0.0


def is_relevant_candidate(
    opinion: str,
    content: str,
    section_title: Optional[str] = None,
    document_title: Optional[str] = None,
    role_keywords: Optional[list[str]] = None,
    config: Optional[EvidenceLinkingConfig] = None,
) -> bool:
    """평가 의견과 청크(본문/섹션 제목/역할 키워드)가 관련 있는지 검사한다.

    의견에서 의미 있는 키워드를 하나도 뽑지 못한 경우(너무 일반적인 의견)는
    판단 근거가 없으므로 필터링하지 않고 통과시킨다.
    """
    cfg = config or EvidenceLinkingConfig()
    opinion_keywords = extract_keywords(opinion)
    if not opinion_keywords:
        return True

    min_overlap = cfg.min_keyword_overlap

    if _stem_overlap_count(opinion_keywords, content) >= min_overlap:
        return True
    if _stem_overlap_count(opinion_keywords, section_title) >= min_overlap:
        return True
    if role_keywords and content and any(keyword and keyword in content for keyword in role_keywords):
        return True

    score = calculate_relevance_score(opinion, content, section_title, document_title, role_keywords)
    return score >= cfg.min_relevance_score


__all__ = [
    "STOPWORDS",
    "extract_keywords",
    "calculate_relevance_score",
    "is_relevant_candidate",
]
