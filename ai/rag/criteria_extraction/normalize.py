"""
배점(weight)/평가항목 이름 정규화 유틸.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional

_WEIGHT_NUMBER_RE = re.compile(r"(\d+(?:\.\d+)?)")
_NO_WEIGHT_MARKERS = ("미공개", "비공개", "별도", "추후", "해당없음", "미정")


def normalize_weight(raw: object) -> Optional[float]:
    """LLM이 뽑아준 weight 원본 값을 숫자로 정규화한다.

    이미 숫자면 그대로 쓰고, "20점"/"20 점"/"20%"처럼 숫자가 섞인 문자열이면 첫
    숫자만 뽑는다. 숫자를 찾을 수 없거나(None/빈 문자열) "배점 별도 공고" 같은
    미공개 표현이면 None을 반환한다 — 배점을 추측해서 채우지 않는다.
    """
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if not isinstance(raw, str):
        return None

    text = raw.strip()
    if not text:
        return None
    if any(marker in text for marker in _NO_WEIGHT_MARKERS):
        return None

    match = _WEIGHT_NUMBER_RE.search(text)
    if match is None:
        return None
    return float(match.group(1))


def normalize_criterion_key(name: str) -> str:
    """중복 제거용 이름 정규화 — 전각/반각·공백·대소문자 차이를 무시하고 비교한다."""
    normalized = unicodedata.normalize("NFKC", name)
    return re.sub(r"\s+", "", normalized).lower()
