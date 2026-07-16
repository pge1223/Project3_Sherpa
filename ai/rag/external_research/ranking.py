"""
External Evidence Ranking (RAG-007)
=========================================
semantic_score, role_score, criteria_score, freshness_score를 config 가중치로
조합해 final_score를 계산한다. 전부 규칙 기반이며 LLM을 사용하지 않는다.
"""

from typing import Sequence

# 자료에 supported_roles가 비어 있으면(범용 자료) 특정 역할에 유리하거나 불리하게
# 만들지 않기 위해 중립 점수를 준다.
NEUTRAL_ROLE_SCORE: float = 0.5


def compute_role_score(supported_roles: Sequence[str], reviewer_role: str) -> float:
    """reviewer_role이 supported_roles에 있으면 1.0, 없으면 0.0. supported_roles가
    비어 있으면(제한 없음) 0.5(중립)."""
    if not supported_roles:
        return NEUTRAL_ROLE_SCORE
    normalized = {r.strip().lower() for r in supported_roles}
    return 1.0 if reviewer_role.strip().lower() in normalized else 0.0


def compute_criteria_score(evidence_criteria: Sequence[str], requested_criteria: Sequence[str]) -> float:
    """요청 평가 기준 중 자료의 evaluation_criteria와 겹치는 비율.
    자료에 평가 기준이 아예 없으면(범용 자료) 0.0이 아니라 중립값을 준다 —
    특정 평가 기준을 인용하지 않았다고 해서 무조건 무관하다고 볼 수는 없기 때문이다."""
    if not requested_criteria:
        return 0.0
    if not evidence_criteria:
        return NEUTRAL_ROLE_SCORE
    evidence_norm = {c.strip().lower() for c in evidence_criteria}
    requested_norm = {c.strip().lower() for c in requested_criteria}
    overlap = evidence_norm & requested_norm
    return len(overlap) / len(requested_norm)


def compute_final_score(
    *,
    semantic_score: float,
    role_score: float,
    criteria_score: float,
    freshness_score: float,
    semantic_weight: float,
    role_weight: float,
    criteria_weight: float,
    freshness_weight: float,
) -> float:
    """가중합. 각 입력 점수가 [0,1] 범위라는 전제 하에 결과도 대체로 [0,1] 범위가 되도록
    가중치 합이 1에 가깝게 설계돼 있다(config 기본값 0.55+0.20+0.15+0.10=1.0). 값 자체를
    강제로 clamp하지는 않는다 — 가중치를 다르게 설정한 호출자의 의도를 존중한다."""
    return (
        semantic_score * semantic_weight
        + role_score * role_weight
        + criteria_score * criteria_weight
        + freshness_score * freshness_weight
    )


__all__ = ["compute_role_score", "compute_criteria_score", "compute_final_score", "NEUTRAL_ROLE_SCORE"]
