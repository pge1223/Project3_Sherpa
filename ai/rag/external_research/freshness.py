"""
External Evidence Freshness Judgement (RAG-007)
======================================================
자료 기준일(reference_date, 없으면 published_at)과 오늘 날짜(또는 요청의
reference_date)를 비교해 최신성 상태와 점수를 계산한다. 날짜를 확인할 수 없으면
"최신 자료"로 임의 판정하지 않는다 — UNKNOWN + 낮은 점수.
"""

from datetime import date, datetime
from typing import Optional

from ai.rag.external_research.config import FreshnessConfig
from ai.rag.external_research.schemas import ExternalEvidenceType, FreshnessStatus

# 날짜가 없는 자료는 "최신일 수도 있다"는 가정을 하지 않는다 — 고정된 낮은 점수를 준다.
UNKNOWN_FRESHNESS_SCORE: float = 0.2


def parse_iso_date(value: Optional[str]) -> Optional[date]:
    """YYYY-MM-DD 형식만 인정한다. 형식이 다르거나 값이 없으면 None (임의 생성하지 않음)."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def compute_freshness(
    *,
    evidence_type: ExternalEvidenceType,
    reference_date: Optional[str],
    published_at: Optional[str],
    as_of: Optional[date] = None,
    config: Optional[FreshnessConfig] = None,
) -> tuple[FreshnessStatus, float]:
    """(FreshnessStatus, freshness_score[0,1]) 튜플을 반환한다.
    reference_date를 우선하고, 없으면 published_at을 쓴다. 둘 다 없으면 UNKNOWN."""
    cfg = config or FreshnessConfig()
    baseline = as_of or date.today()

    chosen = parse_iso_date(reference_date) or parse_iso_date(published_at)
    if chosen is None:
        return FreshnessStatus.UNKNOWN, UNKNOWN_FRESHNESS_SCORE

    age_days = (baseline - chosen).days
    if age_days < 0:
        # 미래 날짜(시계열 오류 등)는 방어적으로 "현재"로 취급한다.
        age_days = 0

    threshold = cfg.threshold_for(evidence_type)

    if age_days <= threshold:
        status = FreshnessStatus.CURRENT
        score = 1.0 if threshold == 0 else max(0.0, 1.0 - (age_days / threshold) * 0.3)
    elif age_days <= threshold * 1.5:
        status = FreshnessStatus.AGING
        # threshold~1.5*threshold 구간을 0.7 -> 0.4로 선형 감소
        span = threshold * 0.5
        progressed = (age_days - threshold) / span if span else 1.0
        score = max(0.4, 0.7 - 0.3 * progressed)
    else:
        status = FreshnessStatus.STALE
        span = threshold * 1.5
        progressed = min((age_days - threshold * 1.5) / span, 1.0) if span else 1.0
        score = max(0.0, 0.3 - 0.3 * progressed)

    return status, round(score, 4)


__all__ = ["compute_freshness", "parse_iso_date", "UNKNOWN_FRESHNESS_SCORE"]
