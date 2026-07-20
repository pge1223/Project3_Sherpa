"""
LLM 응답 정규화 유틸 (confidence 숫자화, 라벨 문자열 정규화).
"""

from __future__ import annotations

import re
from typing import Optional

from ai.rag.domain_classification.schemas import KNOWN_DOMAIN_LABELS, DomainLabel

_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_NUMBER_RE = re.compile(r"(\d+(?:\.\d+)?)")


def normalize_confidence(raw: object) -> Optional[float]:
    """LLM이 준 confidence 원본 값을 [0.0, 1.0] 범위의 float로 정규화한다.

    "80%"는 0.8로, "0.8"/0.8/80(1보다 크면 백분율로 간주)은 각각 0.8로 해석한다.
    숫자를 전혀 찾을 수 없으면 None을 반환한다 — 이 경우 서비스는 확신도를
    신뢰할 수 없다고 보고 보수적으로 처리한다(추측해서 채우지 않음).
    """
    if raw is None or isinstance(raw, bool):
        return None

    if isinstance(raw, (int, float)):
        value = float(raw)
    elif isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        percent_match = _PERCENT_RE.search(text)
        if percent_match:
            value = float(percent_match.group(1)) / 100.0
            return _clamp(value)
        number_match = _NUMBER_RE.search(text)
        if number_match is None:
            return None
        value = float(number_match.group(1))
    else:
        return None

    if value > 1.0:
        value = value / 100.0  # 1보다 크면 0~100 스케일로 간주
    return _clamp(value)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def normalize_domain_label(raw: object) -> Optional[DomainLabel]:
    """LLM이 준 domain 라벨 문자열을 KNOWN_DOMAIN_LABELS 중 하나로 정규화한다.
    대소문자/공백 차이만 허용하고, 그 외에는 매칭시키지 않는다(오분류를 라벨
    유사도로 억지로 끼워맞추지 않기 위함) — 알 수 없으면 None."""
    if not isinstance(raw, str):
        return None
    normalized = raw.strip().lower()
    for label in KNOWN_DOMAIN_LABELS:
        if label.value == normalized:
            return label
    return None
