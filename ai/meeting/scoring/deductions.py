# 작성자: 경이
# 목적: 필수항목 누락 감점 규칙(MTG-003). rubric 에서 required=true 인데 어떤 위원도
#       채점하지 않은 기준을 찾아 penalty 항목으로 만든다. 감점 근거는 RPT-006 점수 설명에 재사용.
# import: 표준 라이브러리 decimal. (외부 의존성 없음)

from __future__ import annotations

from decimal import Decimal
from typing import Any


def compute_penalties(
    rubric: dict[str, Any],
    scored_criterion_ids: set[str],
    missing_required_penalty: Decimal = Decimal(0),
) -> list[dict[str, Any]]:
    """필수항목 누락 감점 목록을 반환한다.

    required=true 기준이 어떤 위원에게도 채점되지 않으면(scored_criterion_ids 에 없음)
    penalty 항목을 만든다. 기본 감점액은 0이다 — 누락 기준은 이미 raw_score 0으로 배점만큼
    총점에 반영되지 않으므로, penalty 는 '왜 0인지'를 설명하는 표식 역할을 한다. 팀이 추가
    감점을 원하면 missing_required_penalty 로 조정한다.
    """
    penalties: list[dict[str, Any]] = []
    for c in rubric["criteria"]:
        if c.get("required") and c["criterion_id"] not in scored_criterion_ids:
            penalties.append(
                {
                    "type": "missing_required",
                    "criterion_id": c["criterion_id"],
                    "amount": _num(missing_required_penalty),
                    "reason": f"필수 항목 '{c['criterion_name']}'에 대한 위원 평가가 없습니다.",
                }
            )
    return penalties


def _num(value: Decimal) -> int | float:
    """정수면 int, 아니면 float 로 정규화한다(JSON 직렬화·비교 일관성)."""
    if value == value.to_integral_value():
        return int(value)
    return float(value)
