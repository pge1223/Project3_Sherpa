"""
Role-Aware Reranker
======================
RAG-002 SearchResult 후보 목록에 역할 관련도(role_score)를 계산해 붙이고,
semantic_score와 결합한 final_score 기준으로 재정렬해 RoleSearchResult를 만든다.
중복/과도 중첩 청크를 제거하고, 점수가 비슷할 때는 서로 다른 section을 우선해
top_k를 뽑는다 — 이 모든 처리는 이 함수 1회 호출(= search_by_role() 1회 = 하나의
(persona, criterion) 검색) 범위 안에서만 이뤄진다. 다른 persona/criterion의 검색
결과와는 전혀 공유하지 않으므로, 서로 다른 persona가 같은 근거를 쓰는 것은 그대로 허용된다.
"""

import re
from typing import Optional

from ai.rag.retrieval.schemas import SearchResult
from ai.rag.role_retrieval.config import RoleRerankConfig
from ai.rag.role_retrieval.schemas import RoleProfile, RoleSearchResult

_WHITESPACE_RE = re.compile(r"\s+")


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


def _normalize_for_dedup(text: str) -> str:
    """공백/줄바꿈 차이만 무시하도록 정규화한다(단어 자체는 바꾸지 않음)."""
    return _WHITESPACE_RE.sub(" ", text or "").strip().lower()


def _word_overlap_coefficient(a: str, b: str) -> float:
    """두 정규화 텍스트의 단어 집합 기준 overlap coefficient(교집합 크기 / 더 작은 집합
    크기)를 계산한다. Jaccard(교집합/합집합)가 아니라 overlap coefficient를 쓰는 이유는,
    이 값이 걸러내려는 대상이 "두 청크가 전반적으로 비슷하다"가 아니라 chunk_overlap으로
    인해 "한쪽이 다른 쪽 내용을 대부분 포함한다"는 포함 관계이기 때문이다 — 두 집합 크기
    차이가 클 때 Jaccard는 과소평가되지만 overlap coefficient는 포함 관계를 그대로 반영한다."""
    words_a, words_b = set(a.split()), set(b.split())
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / min(len(words_a), len(words_b))


def _deduplicate(scored: list[RoleSearchResult], config: RoleRerankConfig) -> list[RoleSearchResult]:
    """final_score 내림차순으로 이미 정렬된 목록에서, 동일 chunk_id/공백만 다른 동일 텍스트/
    overlap coefficient가 높아 대부분 겹치는 텍스트를 점수가 더 낮은 쪽부터 제거한다(먼저
    나온, 즉 점수가 더 높은 결과를 남긴다)."""
    kept: list[RoleSearchResult] = []
    kept_normalized: list[str] = []
    seen_chunk_ids: set[str] = set()

    for item in scored:
        if item.chunk_id in seen_chunk_ids:
            continue

        normalized = _normalize_for_dedup(item.content)
        is_duplicate = any(
            normalized == kept_norm
            or _word_overlap_coefficient(normalized, kept_norm) >= config.duplicate_content_overlap_coefficient
            for kept_norm in kept_normalized
        )
        if is_duplicate:
            continue

        seen_chunk_ids.add(item.chunk_id)
        kept_normalized.append(normalized)
        kept.append(item)

    return kept


def _select_with_section_diversity(
    deduplicated: list[RoleSearchResult], top_k: int, config: RoleRerankConfig
) -> list[RoleSearchResult]:
    """final_score 내림차순으로 정렬된(중복 제거 완료) 목록에서 top_k를 뽑는다. 점수가
    diversity_score_epsilon 이내로 비슷한 후보들 사이에서는, 이미 뽑힌 section과 다른
    section을 가진 후보를 우선한다 — section이 없거나(None) 이미 다양성을 만족하면 점수
    순서를 그대로 따른다."""
    if len(deduplicated) <= top_k:
        return deduplicated

    remaining = list(deduplicated)
    selected: list[RoleSearchResult] = []
    selected_sections: set[str] = set()

    while remaining and len(selected) < top_k:
        best_score = remaining[0].final_score
        window = [r for r in remaining if best_score - r.final_score <= config.diversity_score_epsilon]

        chosen = next(
            (
                r for r in window
                if r.metadata.get("section_title") is not None
                and r.metadata.get("section_title") not in selected_sections
            ),
            window[0],
        )
        selected.append(chosen)
        section_title = chosen.metadata.get("section_title")
        if section_title is not None:
            selected_sections.add(section_title)
        remaining.remove(chosen)

    return selected


def rerank_by_role(
    candidates: list[SearchResult],
    role_profile: Optional[RoleProfile],
    role_id: Optional[str],
    config: RoleRerankConfig,
    top_k: int,
) -> list[RoleSearchResult]:
    """후보 SearchResult 목록 -> role_score/final_score 계산 -> 내림차순 정렬 ->
    중복/과도 중첩 제거 -> section 다양성을 고려한 top_k 선택."""
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

    deduplicated = _deduplicate(scored, config)
    return _select_with_section_diversity(deduplicated, top_k, config)
