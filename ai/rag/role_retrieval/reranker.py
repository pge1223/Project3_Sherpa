"""
Role-Aware Reranker
======================
RAG-002 SearchResult 후보 목록에 역할 관련도(role_score)를 계산해 붙이고,
semantic_score와 결합한 final_score 기준으로 재정렬해 RoleSearchResult를 만든다.
"""

from typing import Optional

from ai.rag.retrieval.schemas import SearchResult
from ai.rag.role_retrieval.config import RoleRerankConfig
from ai.rag.role_retrieval.schemas import RoleProfile, RoleSearchResult


def _count_keyword_hits(text: str, keywords: list[str]) -> int:
    if not text or not keywords:
        return 0
    return sum(1 for keyword in keywords if keyword and keyword in text)


def compute_role_score(
    result: SearchResult,
    role_profile: Optional[RoleProfile],
    config: RoleRerankConfig,
) -> float:
    """content/section_title/document_title에서 역할 키워드 매칭 건수를 점수화한다.
    role_profile이 없으면(일반 검색) role_score는 항상 0.0."""
    if role_profile is None:
        return 0.0

    content = result.content or ""
    section_title = result.metadata.get("section_title") or ""
    document_title = result.metadata.get("document_title") or ""

    content_hits = min(_count_keyword_hits(content, role_profile.focus_keywords), config.max_content_hits)
    section_hits = min(
        _count_keyword_hits(section_title, role_profile.section_keywords)
        + _count_keyword_hits(section_title, role_profile.focus_keywords),
        config.max_section_hits,
    )
    title_hits = min(_count_keyword_hits(document_title, role_profile.focus_keywords), config.max_title_hits)

    raw_score = (
        content_hits * config.content_hit_weight
        + section_hits * config.section_hit_weight
        + title_hits * config.title_hit_weight
    )
    return min(raw_score, config.max_role_score)


def combine_scores(
    semantic_score: Optional[float],
    role_score: float,
    config: RoleRerankConfig,
) -> float:
    semantic = semantic_score if semantic_score is not None else 0.0
    return semantic * config.semantic_weight + role_score * config.role_weight


def rerank_by_role(
    candidates: list[SearchResult],
    role_profile: Optional[RoleProfile],
    role_id: Optional[str],
    config: RoleRerankConfig,
    top_k: int,
) -> list[RoleSearchResult]:
    """후보 SearchResult 목록 -> role_score/final_score 계산 -> 내림차순 정렬 -> top_k."""
    scored: list[RoleSearchResult] = []
    for candidate in candidates:
        role_score = compute_role_score(candidate, role_profile, config)
        final_score = combine_scores(candidate.score, role_score, config)
        scored.append(RoleSearchResult(
            record_id=candidate.record_id,
            chunk_id=candidate.chunk_id,
            document_id=candidate.document_id,
            content=candidate.content,
            distance=candidate.distance,
            semantic_score=candidate.score,
            role_score=role_score,
            final_score=final_score,
            role_id=role_id,
            metadata=candidate.metadata,
        ))
    scored.sort(key=lambda item: item.final_score, reverse=True)
    return scored[:top_k]
