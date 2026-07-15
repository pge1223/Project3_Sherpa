# 작성자: 경이
# 목적: rubric 에서 항목별 가중치를 해석한다(MTG-003). criterion_owner 방식에서는
#       각 기준의 배점(max_score)이 곧 가중치다. weighted_average 방식 확장 여지를 남긴다.
# import: 표준 라이브러리 decimal. (외부 의존성 없음)

from __future__ import annotations

from decimal import Decimal
from typing import Any


def criterion_max_scores(rubric: dict[str, Any]) -> dict[str, Decimal]:
    """criterion_id -> 배점(max_score) Decimal 매핑."""
    return {c["criterion_id"]: Decimal(str(c["max_score"])) for c in rubric["criteria"]}


def total_max_score(rubric: dict[str, Any]) -> Decimal:
    """rubric 전체 배점 합. total_max_score 필드가 있으면 정합성을 검증한다."""
    computed = sum(criterion_max_scores(rubric).values(), Decimal(0))
    declared = rubric.get("total_max_score")
    if declared is not None and Decimal(str(declared)) != computed:
        raise ValueError(
            f"rubric total_max_score({declared}) 와 기준 배점 합({computed})이 일치하지 않습니다."
        )
    return computed


def resolve_weights(rubric: dict[str, Any], method: str = "criterion_owner") -> dict[str, Decimal]:
    """항목별 가중치를 반환한다.
    - criterion_owner: 가중치 = 배점(max_score). 총점은 항목 점수의 단순 합(배점 스케일).
    - weighted_average: 가중치 = 배점 / 전체 배점(정규화). (확장용)
    """
    max_scores = criterion_max_scores(rubric)
    if method == "criterion_owner":
        return dict(max_scores)
    if method == "weighted_average":
        total = total_max_score(rubric)
        if total == 0:
            raise ValueError("전체 배점이 0이라 가중치를 정규화할 수 없습니다.")
        return {cid: (ms / total) for cid, ms in max_scores.items()}
    raise ValueError(f"알 수 없는 계산 방식: {method!r}")
