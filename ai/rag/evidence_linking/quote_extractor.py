"""
Rule-Based Quote Extraction
===============================
청크 원문(content)에서 평가 의견과 관련성이 높은 문장 일부를 그대로 잘라 인용문으로
쓴다. LLM 호출 없음 — 원문에 존재하지 않는 문장은 절대 생성하지 않는다.
"""

import re
from typing import Optional

from ai.rag.evidence_linking.config import EvidenceLinkingConfig

# 문장 종결 기호(., ?, !) 뒤 공백 기준으로 분리한다. 한국어 종결어미 "다.", "니다." 등도
# 결국 마침표로 끝나므로 이 규칙 하나로 함께 처리된다.
_SENTENCE_END_RE = re.compile(r"(?<=[.?!])\s+")

# 키워드 중복 매칭에 쓰는 토큰: 한글/영문/숫자 2자 이상 (조사 등 1자 토큰의 잡음을 줄임)
_TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9]+")


def split_sentences(content: str) -> list[str]:
    """content를 문장 단위로 분리한다. 각 문장은 content의 부분 문자열이다."""
    if not content or not content.strip():
        return []
    normalized = content.strip()
    parts = _SENTENCE_END_RE.split(normalized)
    return [p.strip() for p in parts if p.strip()]


def _tokenize(text: str) -> set[str]:
    return {token for token in _TOKEN_RE.findall(text) if len(token) >= 2}


def select_best_sentence(
    opinion: str,
    sentences: list[str],
    role_keywords: Optional[list[str]] = None,
) -> Optional[str]:
    """opinion과 공통 키워드가 가장 많은 문장을 고른다. 관련성이 전혀 없으면 None."""
    if not sentences:
        return None

    opinion_tokens = _tokenize(opinion)
    keywords = role_keywords or []

    best_sentence: Optional[str] = None
    best_score = 0
    for sentence in sentences:
        overlap = len(opinion_tokens & _tokenize(sentence))
        role_hits = sum(1 for keyword in keywords if keyword and keyword in sentence)
        # 의견과의 공통 키워드를 역할 키워드보다 우선 반영한다.
        score = overlap * 2 + role_hits
        if score > best_score:
            best_score = score
            best_sentence = sentence

    return best_sentence if best_score > 0 else None


def _truncate(text: str, max_length: int) -> str:
    if len(text) <= max_length or max_length <= 1:
        return text
    return text[: max_length - 1].rstrip() + "…"


def extract_quote(
    content: str,
    opinion: str,
    config: EvidenceLinkingConfig,
    role_keywords: Optional[list[str]] = None,
) -> str:
    """content에서 opinion과 가장 관련 있는 인용문을 추출한다.
    관련 문장이 없으면 content 앞부분을 quote_context_length만큼 잘라 반환한다."""
    if not content or not content.strip():
        return ""

    sentences = split_sentences(content)
    best_sentence = select_best_sentence(opinion, sentences, role_keywords)

    if best_sentence is not None:
        return _truncate(best_sentence, config.quote_max_length)

    fallback = content.strip()[: config.quote_context_length]
    return _truncate(fallback, config.quote_max_length)
