"""
Evidence Sufficiency Service (RAG-005)
===========================================
회의 파이프라인(다른 담당자 영역)이 호출할 공개 인터페이스. RAG-003
RoleSearchResponse/RoleSearchResult 또는 RAG-004 LinkedEvaluation을 받아
근거 충분도를 판정한다. 새 검색, Chroma, 임베딩, LLM 호출을 하지 않는다.
"""

import logging
from typing import Optional, Sequence

from ai.rag.evidence_linking.schemas import LinkedEvaluation
from ai.rag.evidence_sufficiency.config import EvidenceSufficiencyConfig
from ai.rag.evidence_sufficiency.evaluator import (
    CandidateEvaluation,
    determine_status,
    evaluate_candidates,
)
from ai.rag.evidence_sufficiency.prompt_guard import build_prompt_guard
from ai.rag.evidence_sufficiency.schemas import (
    EvidenceReasonCode,
    EvidenceSufficiencyResult,
    EvidenceSufficiencyStatus,
)
from ai.rag.role_retrieval.schemas import RoleSearchResponse, RoleSearchResult

logger = logging.getLogger(__name__)

_REASON_TEXT: dict[EvidenceReasonCode, str] = {
    EvidenceReasonCode.NO_RESULTS: "검색된 근거가 없습니다.",
    EvidenceReasonCode.NO_VALID_EVIDENCE: "유효한 근거가 없습니다 (출처 정보 또는 본문 누락).",
    EvidenceReasonCode.NO_QUALIFIED_EVIDENCE: "기준을 충족하는 근거가 없습니다.",
    EvidenceReasonCode.BELOW_MIN_SCORE: "최소 검색 점수를 충족하는 관련 근거가 없습니다.",
    EvidenceReasonCode.TOO_FEW_EVIDENCE: "권장 근거 개수보다 적은 근거만 확인되었습니다.",
    EvidenceReasonCode.DUPLICATE_EVIDENCE_ONLY: "중복된 근거만 존재하여 실질적인 근거 수가 부족합니다.",
    EvidenceReasonCode.EMPTY_CONTENT: "본문이 비어 있거나 너무 짧은 근거가 포함되어 있습니다.",
    EvidenceReasonCode.MISSING_SOURCE_ID: "문서 ID 또는 청크 ID가 없는 근거가 포함되어 있습니다.",
    EvidenceReasonCode.NO_LINKED_EVIDENCE: "연결된 근거가 없습니다.",
}


def _build_reasons(reason_codes: list[EvidenceReasonCode]) -> list[str]:
    return [_REASON_TEXT[code] for code in reason_codes if code in _REASON_TEXT]


class EvidenceSufficiencyService:
    """RAG-003/RAG-004 결과를 입력받아 EvidenceSufficiencyResult를 반환하는 통합 인터페이스."""

    def __init__(self, default_config: Optional[EvidenceSufficiencyConfig] = None):
        self._default_config = default_config or EvidenceSufficiencyConfig()

    def assess_search_results(
        self,
        search_results: Optional[Sequence[RoleSearchResult]],
        *,
        role_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        config: Optional[EvidenceSufficiencyConfig] = None,
    ) -> EvidenceSufficiencyResult:
        """RAG-003 RoleSearchResult 목록(또는 호환 duck-typed 객체)의 충분도를 판정한다."""
        effective_config = config or self._default_config
        total_input = len(search_results) if search_results else 0

        logger.info(
            "[EVIDENCE_SUFFICIENCY_START] trace_id=%s role_id=%s total_evidence_count=%d",
            trace_id,
            role_id,
            total_input,
        )

        evaluation = evaluate_candidates(search_results, effective_config)
        result = self._build_result(evaluation, effective_config, role_id=role_id, trace_id=trace_id)
        self._log_completion(result)
        return result

    def assess_role_response(
        self,
        response: RoleSearchResponse,
        *,
        trace_id: Optional[str] = None,
        config: Optional[EvidenceSufficiencyConfig] = None,
    ) -> EvidenceSufficiencyResult:
        """RAG-003 RoleSearchResponse 편의 진입점. response.results/response.role_id를 그대로 사용한다."""
        return self.assess_search_results(
            response.results,
            role_id=response.role_id,
            trace_id=trace_id,
            config=config,
        )

    def assess_linked_evaluation(
        self,
        linked_evaluation: LinkedEvaluation,
        *,
        trace_id: Optional[str] = None,
        config: Optional[EvidenceSufficiencyConfig] = None,
    ) -> EvidenceSufficiencyResult:
        """RAG-004 LinkedEvaluation의 충분도를 판정한다.
        has_evidence=False이거나 evidence가 비어 있으면 즉시 insufficient로 반환한다."""
        effective_config = config or self._default_config
        role_id = linked_evaluation.role_id
        total_input = len(linked_evaluation.evidence)

        logger.info(
            "[EVIDENCE_SUFFICIENCY_START] trace_id=%s role_id=%s total_evidence_count=%d",
            trace_id,
            role_id,
            total_input,
        )

        if not linked_evaluation.has_evidence or not linked_evaluation.evidence:
            result = self._build_no_linked_evidence_result(role_id=role_id, trace_id=trace_id)
            self._log_completion(result)
            return result

        evaluation = evaluate_candidates(linked_evaluation.evidence, effective_config)
        result = self._build_result(evaluation, effective_config, role_id=role_id, trace_id=trace_id)
        self._log_completion(result)
        return result

    def _build_no_linked_evidence_result(
        self, *, role_id: Optional[str], trace_id: Optional[str]
    ) -> EvidenceSufficiencyResult:
        status = EvidenceSufficiencyStatus.INSUFFICIENT
        reason_codes = [EvidenceReasonCode.NO_LINKED_EVIDENCE]
        return EvidenceSufficiencyResult(
            status=status,
            is_sufficient=False,
            allow_definitive_judgment=False,
            allow_numeric_score=False,
            role_id=role_id,
            trace_id=trace_id,
            total_evidence_count=0,
            valid_evidence_count=0,
            qualified_evidence_count=0,
            duplicate_count=0,
            invalid_evidence_count=0,
            max_score=None,
            average_score=None,
            unique_document_count=0,
            unique_section_count=0,
            qualified_document_ids=[],
            qualified_chunk_ids=[],
            reason_codes=reason_codes,
            reasons=_build_reasons(reason_codes),
            prompt_guard=build_prompt_guard(status),
        )

    def _build_result(
        self,
        evaluation: CandidateEvaluation,
        config: EvidenceSufficiencyConfig,
        *,
        role_id: Optional[str],
        trace_id: Optional[str],
    ) -> EvidenceSufficiencyResult:
        qualified_count = len(evaluation.qualified)
        status = determine_status(qualified_count, config)

        reason_codes = list(evaluation.reason_codes)
        if status == EvidenceSufficiencyStatus.PARTIAL and EvidenceReasonCode.TOO_FEW_EVIDENCE not in reason_codes:
            reason_codes.append(EvidenceReasonCode.TOO_FEW_EVIDENCE)

        if status == EvidenceSufficiencyStatus.INSUFFICIENT:
            is_sufficient, allow_definitive, allow_numeric = False, False, False
        elif status == EvidenceSufficiencyStatus.PARTIAL:
            is_sufficient = False
            allow_definitive = config.partial_allows_definitive_judgment
            allow_numeric = config.partial_allows_numeric_score
        else:
            is_sufficient = True
            allow_definitive = True
            allow_numeric = config.sufficient_allows_numeric_score

        scores = [candidate.score for candidate in evaluation.qualified]
        max_score = max(scores) if scores else None
        average_score = (sum(scores) / len(scores)) if scores else None

        qualified_document_ids = [candidate.document_id for candidate in evaluation.qualified]
        qualified_chunk_ids = [candidate.chunk_id for candidate in evaluation.qualified]
        unique_document_count = len(set(qualified_document_ids))
        unique_section_count = len(
            {candidate.section_title for candidate in evaluation.qualified if candidate.section_title}
        )

        return EvidenceSufficiencyResult(
            status=status,
            is_sufficient=is_sufficient,
            allow_definitive_judgment=allow_definitive,
            allow_numeric_score=allow_numeric,
            role_id=role_id,
            trace_id=trace_id,
            total_evidence_count=evaluation.total_count,
            valid_evidence_count=evaluation.valid_count,
            qualified_evidence_count=qualified_count,
            duplicate_count=evaluation.duplicate_count,
            invalid_evidence_count=evaluation.invalid_count,
            max_score=max_score,
            average_score=average_score,
            unique_document_count=unique_document_count,
            unique_section_count=unique_section_count,
            qualified_document_ids=qualified_document_ids,
            qualified_chunk_ids=qualified_chunk_ids,
            reason_codes=reason_codes,
            reasons=_build_reasons(reason_codes),
            prompt_guard=build_prompt_guard(status),
        )

    def _log_completion(self, result: EvidenceSufficiencyResult) -> None:
        logger.info(
            "[EVIDENCE_SUFFICIENCY_COMPLETE] trace_id=%s role_id=%s status=%s "
            "valid_evidence_count=%d qualified_evidence_count=%d duplicate_count=%d "
            "allow_definitive_judgment=%s allow_numeric_score=%s reason_codes=%s",
            result.trace_id,
            result.role_id,
            result.status.value,
            result.valid_evidence_count,
            result.qualified_evidence_count,
            result.duplicate_count,
            result.allow_definitive_judgment,
            result.allow_numeric_score,
            [code.value for code in result.reason_codes],
        )
        if result.status == EvidenceSufficiencyStatus.INSUFFICIENT:
            logger.warning(
                "[EVIDENCE_INSUFFICIENT] trace_id=%s role_id=%s reason_codes=%s "
                "total_evidence_count=%d qualified_evidence_count=%d",
                result.trace_id,
                result.role_id,
                [code.value for code in result.reason_codes],
                result.total_evidence_count,
                result.qualified_evidence_count,
            )


__all__ = ["EvidenceSufficiencyService"]
