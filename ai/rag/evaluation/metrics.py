"""
Retrieval Evaluation Metrics
===============================
검색 서비스, Chroma, LangGraph 등 외부 의존성과 무관한 순수 함수만 포함한다.
입력은 순위가 매겨진 chunk_id 리스트와 정답 chunk_id 집합, 출력은 float다.

지표 정의 (자세한 설명은 README.md 참고):
- Precision@K = 상위 K개 중 관련 청크 수 / 실제 반환된 상위 K개 수
- Recall@K    = 상위 K개에서 찾은 관련 청크 수 / 전체 정답 청크 수
- Hit Rate@K  = 상위 K개에 정답 청크가 하나라도 있으면 1, 없으면 0
- Reciprocal Rank = 첫 번째 정답 청크 순위(1-indexed)의 역수, 없으면 0
- MRR         = 전체 케이스 Reciprocal Rank의 평균 (runner에서 집계)
- nDCG@K      = binary relevance 기준 DCG@K / IDCG@K
"""

from __future__ import annotations

import math


def deduplicate_ranked_ids(ranked_ids: list[str]) -> list[str]:
    """같은 chunk_id가 여러 번 나타나면 최초 등장한 순위만 유지한다."""
    seen: set[str] = set()
    deduped: list[str] = []
    for chunk_id in ranked_ids:
        if chunk_id not in seen:
            seen.add(chunk_id)
            deduped.append(chunk_id)
    return deduped


def _validate_k(k: int) -> None:
    if k < 1:
        raise ValueError(f"k는 1 이상이어야 합니다: {k}")


def precision_at_k(ranked_ids: list[str], relevant_ids: set[str], k: int) -> float:
    _validate_k(k)
    top_k = deduplicate_ranked_ids(ranked_ids)[:k]
    if not top_k:
        return 0.0
    hits = sum(1 for chunk_id in top_k if chunk_id in relevant_ids)
    return hits / len(top_k)


def recall_at_k(ranked_ids: list[str], relevant_ids: set[str], k: int) -> float:
    _validate_k(k)
    if not relevant_ids:
        return 0.0
    top_k = deduplicate_ranked_ids(ranked_ids)[:k]
    hits = sum(1 for chunk_id in top_k if chunk_id in relevant_ids)
    return hits / len(relevant_ids)


def hit_rate_at_k(ranked_ids: list[str], relevant_ids: set[str], k: int) -> float:
    _validate_k(k)
    top_k = deduplicate_ranked_ids(ranked_ids)[:k]
    return 1.0 if any(chunk_id in relevant_ids for chunk_id in top_k) else 0.0


def reciprocal_rank(ranked_ids: list[str], relevant_ids: set[str]) -> float:
    for rank, chunk_id in enumerate(deduplicate_ranked_ids(ranked_ids), start=1):
        if chunk_id in relevant_ids:
            return 1.0 / rank
    return 0.0


def dcg_at_k(ranked_ids: list[str], relevant_ids: set[str], k: int) -> float:
    _validate_k(k)
    top_k = deduplicate_ranked_ids(ranked_ids)[:k]
    return sum(
        (1.0 if chunk_id in relevant_ids else 0.0) / math.log2(rank + 1)
        for rank, chunk_id in enumerate(top_k, start=1)
    )


def ndcg_at_k(ranked_ids: list[str], relevant_ids: set[str], k: int) -> float:
    _validate_k(k)
    ideal_hit_count = min(len(relevant_ids), k)
    if ideal_hit_count == 0:
        return 0.0
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hit_count + 1))
    if idcg == 0:
        return 0.0
    return dcg_at_k(ranked_ids, relevant_ids, k) / idcg


def mean_reciprocal_rank(reciprocal_ranks: list[float]) -> float:
    if not reciprocal_ranks:
        return 0.0
    return sum(reciprocal_ranks) / len(reciprocal_ranks)
