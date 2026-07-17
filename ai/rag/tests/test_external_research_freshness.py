"""
Unit Tests for ai.rag.external_research.freshness (RAG-007)
==================================================================
"""

from datetime import date, timedelta

from ai.rag.external_research.config import FreshnessConfig
from ai.rag.external_research.freshness import UNKNOWN_FRESHNESS_SCORE, compute_freshness, parse_iso_date
from ai.rag.external_research.schemas import ExternalEvidenceType


def _date_str(days_ago: int, as_of: date) -> str:
    return (as_of - timedelta(days=days_ago)).isoformat()


class TestParseIsoDate:
    def test_valid_date_parsed(self):
        assert parse_iso_date("2025-12-31") == date(2025, 12, 31)

    def test_none_returns_none(self):
        assert parse_iso_date(None) is None

    def test_invalid_format_returns_none_not_error(self):
        assert parse_iso_date("2025/12/31") is None
        assert parse_iso_date("not a date") is None


class TestComputeFreshness:
    def test_recent_reference_date_is_current(self):
        as_of = date(2026, 1, 1)
        status, score = compute_freshness(
            evidence_type=ExternalEvidenceType.STATISTICS,
            reference_date=_date_str(30, as_of),
            published_at=None,
            as_of=as_of,
        )
        assert status.value == "current"
        assert score > 0.5

    def test_very_old_reference_date_is_stale(self):
        as_of = date(2026, 1, 1)
        status, score = compute_freshness(
            evidence_type=ExternalEvidenceType.STATISTICS,
            reference_date=_date_str(365 * 10, as_of),
            published_at=None,
            as_of=as_of,
        )
        assert status.value == "stale"
        assert score < 0.4

    def test_mid_range_is_aging(self):
        config = FreshnessConfig(threshold_days={ExternalEvidenceType.STATISTICS: 100})
        as_of = date(2026, 1, 1)
        status, score = compute_freshness(
            evidence_type=ExternalEvidenceType.STATISTICS,
            reference_date=_date_str(120, as_of),  # 100 < 120 <= 150
            published_at=None,
            as_of=as_of,
            config=config,
        )
        assert status.value == "aging"

    def test_no_dates_returns_unknown(self):
        status, score = compute_freshness(
            evidence_type=ExternalEvidenceType.STATISTICS, reference_date=None, published_at=None
        )
        assert status.value == "unknown"
        assert score == UNKNOWN_FRESHNESS_SCORE

    def test_unknown_score_is_not_high(self):
        _status, score = compute_freshness(
            evidence_type=ExternalEvidenceType.STATISTICS, reference_date=None, published_at=None
        )
        assert score <= 0.3

    def test_reference_date_preferred_over_published_at(self):
        as_of = date(2026, 1, 1)
        status, score = compute_freshness(
            evidence_type=ExternalEvidenceType.STATISTICS,
            reference_date=_date_str(10, as_of),
            published_at=_date_str(365 * 10, as_of),
            as_of=as_of,
        )
        assert status.value == "current"

    def test_falls_back_to_published_at_when_reference_date_missing(self):
        as_of = date(2026, 1, 1)
        status, _score = compute_freshness(
            evidence_type=ExternalEvidenceType.STATISTICS,
            reference_date=None,
            published_at=_date_str(10, as_of),
            as_of=as_of,
        )
        assert status.value == "current"

    def test_evidence_type_specific_threshold_applied(self):
        as_of = date(2026, 1, 1)
        # 2.2년 전 자료: MARKET(기준 2년) 기준으로는 aging/stale, GUIDELINE(기준 3년) 기준으로는 current.
        age_days = int(365 * 2.2)
        market_status, _ = compute_freshness(
            evidence_type=ExternalEvidenceType.MARKET,
            reference_date=_date_str(age_days, as_of),
            published_at=None,
            as_of=as_of,
        )
        guideline_status, _ = compute_freshness(
            evidence_type=ExternalEvidenceType.GUIDELINE,
            reference_date=_date_str(age_days, as_of),
            published_at=None,
            as_of=as_of,
        )
        assert market_status.value != "current"
        assert guideline_status.value == "current"

    def test_does_not_fabricate_reference_date(self):
        # None을 넘겼을 때 임의의 날짜로 채워지지 않고 그대로 unknown 처리됨을 확인.
        status, _score = compute_freshness(
            evidence_type=ExternalEvidenceType.LAW, reference_date=None, published_at=None
        )
        assert status.value == "unknown"

    def test_future_date_treated_as_current_not_error(self):
        as_of = date(2026, 1, 1)
        future_date = (as_of + timedelta(days=10)).isoformat()
        status, score = compute_freshness(
            evidence_type=ExternalEvidenceType.STATISTICS,
            reference_date=future_date,
            published_at=None,
            as_of=as_of,
        )
        assert status.value == "current"
        assert score >= 0.0
