"""
External Evidence Source Validation (RAG-007)
====================================================
검색 후보(Chroma 색인 결과든 외부 API provider가 반환한 원시 결과든)가 정상 근거로
반환될 수 있는 최소 조건을 만족하는지 확인한다. 여기서 출처 URL/발행기관을 새로
만들어내는 일은 없다 — 오직 candidate.metadata에 이미 들어있는 값만 검사한다.
"""

import re
from typing import Any

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _is_non_blank_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_source_metadata(metadata: dict, *, content: str) -> tuple[bool, list[str]]:
    """섹션 20의 최소 검증 항목을 확인한다. (verified, reasons) 튜플을 반환하며,
    reasons는 verified=False일 때 왜 거부됐는지 설명하는 코드 목록이다."""
    reasons: list[str] = []

    if not _is_non_blank_str(metadata.get("source_url")):
        reasons.append("MISSING_SOURCE_URL")
    if not _is_non_blank_str(metadata.get("publisher")):
        reasons.append("MISSING_PUBLISHER")
    if not _is_non_blank_str(metadata.get("document_id")):
        reasons.append("MISSING_DOCUMENT_ID")
    if not _is_non_blank_str(metadata.get("chunk_id")):
        reasons.append("MISSING_CHUNK_ID")
    if not content or not content.strip():
        reasons.append("EMPTY_CONTENT")

    evidence_type = metadata.get("evidence_type")
    if not _is_non_blank_str(evidence_type):
        reasons.append("MISSING_EVIDENCE_TYPE")

    for date_field in ("reference_date", "published_at", "retrieved_at"):
        value = metadata.get(date_field)
        if value is not None and not _DATE_RE.match(str(value)):
            reasons.append(f"INVALID_DATE_FORMAT:{date_field}")

    return (len(reasons) == 0, reasons)


__all__ = ["validate_source_metadata"]
