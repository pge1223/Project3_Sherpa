"""
External Evidence Field Normalization (RAG-007)
======================================================
색인/검색 파이프라인을 거치며 값의 "형태"만 정리한다(빈 문자열 -> None 등). 원문에
없는 숫자·단위·통계 수치를 추론해서 채워 넣는 로직은 여기에 없다 — 그런 추론은
의도적으로 구현하지 않았다(섹션 19). 통계 수치는 색인 시점에 호출자가 이미 구조화된
값을 넘겼을 때만 그대로 통과시킨다.
"""

from typing import Optional


def _clean_str(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped else None


def normalize_metric_fields(
    metric_name: Optional[str],
    metric_value: Optional[float | str],
    metric_unit: Optional[str],
) -> tuple[Optional[str], Optional[float | str], Optional[str]]:
    """빈 문자열을 None으로 정리하는 것 외에는 값을 바꾸지 않는다. metric_value가 없는데
    metric_name/unit만 있는 경우도 그대로 둔다 — 여기서 값을 지어내지 않는다."""
    name = _clean_str(metric_name)
    unit = _clean_str(metric_unit)
    value = metric_value
    if isinstance(value, str):
        value = _clean_str(value)
    return name, value, unit


__all__ = ["normalize_metric_fields"]
