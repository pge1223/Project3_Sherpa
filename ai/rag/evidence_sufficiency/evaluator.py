"""
Evidence Sufficiency Evaluator (RAG-005)
=============================================
RAG-003 RoleSearchResult 또는 RAG-004 EvidenceSource 목록(둘 다 document_id/
chunk_id/score 계열 속성을 갖는 duck-typed 객체)을 받아 유효 근거 개수, 점수
통계, 중복 개수를 계산하고 sufficient/partial/insufficient 상태를 결정한다.

새 검색이나 LLM 호출 없이 이미 받은 결과만 판정한다. 입력 객체는 어떤 필드도
변경하지 않는다.
"""

import math
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from ai.rag.evidence_linking.linker import resolve_score
from ai.rag.evidence_sufficiency.config import EvidenceSufficiencyConfig
from ai.rag.evidence_sufficiency.schemas import EvidenceReasonCode, EvidenceSufficiencyStatus


@dataclass(frozen=True)
class QualifiedCandidate:
    """유효성/점수/중복 검사를 모두 통과한 근거 1건."""

    document_id: str
    chunk_id: str
    score: float
    section_title: Optional[str] = None
    document_title: Optional[str] = None


@dataclass
class CandidateEvaluation:
    """evaluate_candidates()의 반환값. 상태 판정 전 단계의 원시 통계."""

    total_count: int
    valid_count: int
    invalid_count: int
    duplicate_count: int
    qualified: list[QualifiedCandidate] = field(default_factory=list)
    reason_codes: list[EvidenceReasonCode] = field(default_factory=list)


def _extract_content(candidate: Any) -> Optional[str]:
    """RoleSearchResult는 content, EvidenceSource는 quote를 쓴다."""
    content = getattr(candidate, "content", None)
    if content is not None:
        return content
    return getattr(candidate, "quote", None)


def _safe_score(candidate: Any) -> Optional[float]:
    """resolve_score()로 얻은 값을 안전하게 float로 변환한다.
    문자열, None, NaN, 무한대는 모두 사용 불가능한 점수로 취급해 None을 반환한다."""
    try:
        raw = resolve_score(candidate)
    except Exception:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if math.isnan(value) or math.isinf(value):
        return None
    return value


def _extract_metadata_field(candidate: Any, attr_name: str, metadata_key: str) -> Optional[str]:
    value = getattr(candidate, attr_name, None)
    if value is not None:
        return value
    metadata = getattr(candidate, "metadata", None)
    if isinstance(metadata, dict):
        return metadata.get(metadata_key)
    return None


def _is_valid_candidate(
    candidate: Any, config: EvidenceSufficiencyConfig
) -> tuple[bool, Optional[EvidenceReasonCode]]:
    document_id = getattr(candidate, "document_id", None)
    chunk_id = getattr(candidate, "chunk_id", None)

    if config.require_document_id and not document_id:
        return False, EvidenceReasonCode.MISSING_SOURCE_ID
    if config.require_chunk_id and not chunk_id:
        return False, EvidenceReasonCode.MISSING_SOURCE_ID

    if config.require_non_empty_content:
        content = _extract_content(candidate)
        if not content or not content.strip():
            return False, EvidenceReasonCode.EMPTY_CONTENT
        if len(content.strip()) < config.min_content_length:
            return False, EvidenceReasonCode.EMPTY_CONTENT

    return True, None


def evaluate_candidates(
    candidates: Optional[Sequence[Any]],
    config: EvidenceSufficiencyConfig,
) -> CandidateEvaluation:
    """검색 결과 또는 근거 목록을 유효성 -> 최소 점수 -> 중복 제거 순으로 걸러
    최종 판정 가능한 근거 목록과 통계를 만든다. 입력 candidates를 수정하지 않는다."""
    candidates = list(candidates) if candidates else []
    total_count = len(candidates)

    valid_count = 0
    invalid_count = 0
    below_score_count = 0
    duplicate_count = 0
    saw_missing_id = False
    saw_empty_content = False

    seen_keys: set[tuple[str, str]] = set()
    qualified: list[QualifiedCandidate] = []

    for candidate in candidates:
        is_valid, invalid_reason = _is_valid_candidate(candidate, config)
        if not is_valid:
            invalid_count += 1
            if invalid_reason == EvidenceReasonCode.MISSING_SOURCE_ID:
                saw_missing_id = True
            elif invalid_reason == EvidenceReasonCode.EMPTY_CONTENT:
                saw_empty_content = True
            continue

        valid_count += 1

        score = _safe_score(candidate)
        if score is None or score < config.min_score:
            below_score_count += 1
            continue

        document_id = getattr(candidate, "document_id")
        chunk_id = getattr(candidate, "chunk_id")

        if config.deduplicate_by_document_and_chunk:
            key = (document_id, chunk_id)
            if key in seen_keys:
                duplicate_count += 1
                continue
            seen_keys.add(key)

        qualified.append(
            QualifiedCandidate(
                document_id=document_id,
                chunk_id=chunk_id,
                score=score,
                section_title=_extract_metadata_field(candidate, "section_title", "section_title"),
                document_title=_extract_metadata_field(candidate, "document_title", "document_title"),
            )
        )

    reason_codes: list[EvidenceReasonCode] = []
    if total_count == 0:
        reason_codes.append(EvidenceReasonCode.NO_RESULTS)
    elif valid_count == 0:
        reason_codes.append(EvidenceReasonCode.NO_VALID_EVIDENCE)

    if saw_empty_content:
        reason_codes.append(EvidenceReasonCode.EMPTY_CONTENT)
    if saw_missing_id:
        reason_codes.append(EvidenceReasonCode.MISSING_SOURCE_ID)

    if not qualified and valid_count > 0 and below_score_count > 0:
        reason_codes.append(EvidenceReasonCode.BELOW_MIN_SCORE)

    if duplicate_count > 0 and len(qualified) < config.min_required_evidence:
        reason_codes.append(EvidenceReasonCode.DUPLICATE_EVIDENCE_ONLY)

    if not qualified:
        reason_codes.append(EvidenceReasonCode.NO_QUALIFIED_EVIDENCE)

    return CandidateEvaluation(
        total_count=total_count,
        valid_count=valid_count,
        invalid_count=invalid_count,
        duplicate_count=duplicate_count,
        qualified=qualified,
        reason_codes=reason_codes,
    )


def determine_status(
    qualified_count: int, config: EvidenceSufficiencyConfig
) -> EvidenceSufficiencyStatus:
    """qualified_evidence_count와 설정 기준으로 상태를 결정한다."""
    if qualified_count < config.min_required_evidence:
        return EvidenceSufficiencyStatus.INSUFFICIENT
    if qualified_count < config.preferred_evidence_count:
        return EvidenceSufficiencyStatus.PARTIAL
    return EvidenceSufficiencyStatus.SUFFICIENT


__all__ = [
    "QualifiedCandidate",
    "CandidateEvaluation",
    "evaluate_candidates",
    "determine_status",
]
