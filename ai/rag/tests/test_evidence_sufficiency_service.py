"""
Unit Tests for ai.rag.evidence_sufficiency.service
"""

import copy
import logging

from ai.rag.evidence_linking.schemas import EvidenceSource, LinkedEvaluation
from ai.rag.evidence_sufficiency.config import EvidenceSufficiencyConfig
from ai.rag.evidence_sufficiency.schemas import EvidenceReasonCode, EvidenceSufficiencyStatus
from ai.rag.evidence_sufficiency.service import EvidenceSufficiencyService
from ai.rag.role_retrieval.schemas import RoleSearchResponse, RoleSearchResult


def _role_result(document_id="d1", chunk_id="c1", content="예산 세부 계획 설명입니다.", final_score=0.8, metadata=None) -> RoleSearchResult:
    return RoleSearchResult(
        record_id=chunk_id,
        chunk_id=chunk_id,
        document_id=document_id,
        content=content,
        distance=None,
        semantic_score=0.5,
        role_score=0.2,
        final_score=final_score,
        role_id="finance",
        metadata=metadata or {},
    )


def _role_response(results, role_id="finance") -> RoleSearchResponse:
    return RoleSearchResponse(
        query="예산 계획을 평가해줘",
        expanded_query="예산 계획을 평가해줘",
        role_id=role_id,
        role_name="재무 심사위원",
        project_id="p1",
        document_id=None,
        results=results,
        result_count=len(results),
        warnings=[],
    )


class TestAssessSearchResults:
    def test_sufficient_case_allows_definitive_judgment(self):
        service = EvidenceSufficiencyService()
        results = [
            _role_result(chunk_id="c1", content="예산 산정 근거 청크", final_score=0.82),
            _role_result(chunk_id="c2", content="수익 계획 근거 청크", final_score=0.74),
        ]
        result = service.assess_search_results(results, role_id="finance")
        assert result.status == EvidenceSufficiencyStatus.SUFFICIENT
        assert result.is_sufficient is True
        assert result.allow_definitive_judgment is True
        assert result.allow_numeric_score is True

    def test_partial_case_blocks_definitive_judgment(self):
        service = EvidenceSufficiencyService()
        results = [_role_result(content="예산 산정 근거 청크", final_score=0.82)]
        result = service.assess_search_results(results, role_id="finance")
        assert result.status == EvidenceSufficiencyStatus.PARTIAL
        assert result.allow_definitive_judgment is False
        assert result.allow_numeric_score is False

    def test_insufficient_case_blocks_everything(self):
        service = EvidenceSufficiencyService()
        results = [
            _role_result(chunk_id="c1", content="접수 안내 청크", final_score=0.12),
            _role_result(chunk_id="c2", content="", final_score=0.90),
        ]
        result = service.assess_search_results(results, role_id="finance")
        assert result.status == EvidenceSufficiencyStatus.INSUFFICIENT
        assert result.allow_definitive_judgment is False
        assert result.allow_numeric_score is False
        assert result.is_sufficient is False

    def test_none_search_results_is_insufficient(self):
        service = EvidenceSufficiencyService()
        result = service.assess_search_results(None, role_id="finance")
        assert result.status == EvidenceSufficiencyStatus.INSUFFICIENT
        assert EvidenceReasonCode.NO_RESULTS in result.reason_codes

    def test_result_serializable(self):
        service = EvidenceSufficiencyService()
        results = [_role_result()]
        result = service.assess_search_results(results)
        dumped = result.model_dump()
        assert dumped["status"] == "partial"
        assert isinstance(dumped["reason_codes"], list)

    def test_custom_config_applied(self):
        service = EvidenceSufficiencyService()
        results = [_role_result(final_score=0.82)]
        config = EvidenceSufficiencyConfig(min_required_evidence=1, preferred_evidence_count=1)
        result = service.assess_search_results(results, config=config)
        assert result.status == EvidenceSufficiencyStatus.SUFFICIENT

    def test_input_results_not_mutated(self):
        service = EvidenceSufficiencyService()
        results = [_role_result(final_score=0.82)]
        snapshot = copy.deepcopy(results[0].model_dump())
        service.assess_search_results(results, role_id="finance")
        assert results[0].model_dump() == snapshot


class TestAssessRoleResponse:
    def test_role_id_propagated(self):
        service = EvidenceSufficiencyService()
        response = _role_response([_role_result(final_score=0.9)], role_id="finance")
        result = service.assess_role_response(response)
        assert result.role_id == "finance"

    def test_trace_id_propagated(self):
        service = EvidenceSufficiencyService()
        response = _role_response([_role_result(final_score=0.9)])
        result = service.assess_role_response(response, trace_id="trace-123")
        assert result.trace_id == "trace-123"

    def test_empty_results_response_is_insufficient(self):
        service = EvidenceSufficiencyService()
        response = _role_response([])
        result = service.assess_role_response(response)
        assert result.status == EvidenceSufficiencyStatus.INSUFFICIENT


class TestAssessLinkedEvaluation:
    def test_has_evidence_false_is_insufficient(self):
        service = EvidenceSufficiencyService()
        linked = LinkedEvaluation(opinion="예산 근거가 부족합니다.", has_evidence=False, evidence=[])
        result = service.assess_linked_evaluation(linked)
        assert result.status == EvidenceSufficiencyStatus.INSUFFICIENT
        assert EvidenceReasonCode.NO_LINKED_EVIDENCE in result.reason_codes

    def test_empty_evidence_list_is_insufficient_even_if_flag_wrong(self):
        service = EvidenceSufficiencyService()
        # RAG-004가 잘못된 값을 반환하는 경우까지 방어적으로 처리한다.
        linked = LinkedEvaluation(opinion="예산 근거가 부족합니다.", has_evidence=True, evidence=[])
        result = service.assess_linked_evaluation(linked)
        assert result.status == EvidenceSufficiencyStatus.INSUFFICIENT

    def test_single_valid_evidence_source_is_partial_by_default(self):
        service = EvidenceSufficiencyService()
        linked = LinkedEvaluation(
            opinion="예산 근거가 있습니다.",
            has_evidence=True,
            role_id="finance",
            evidence=[EvidenceSource(document_id="d1", chunk_id="c1", quote="예산 산정 근거 인용문", final_score=0.8)],
        )
        result = service.assess_linked_evaluation(linked)
        assert result.status == EvidenceSufficiencyStatus.PARTIAL
        assert result.allow_definitive_judgment is False

    def test_low_final_score_evidence_excluded(self):
        service = EvidenceSufficiencyService()
        linked = LinkedEvaluation(
            opinion="예산 근거가 있습니다.",
            has_evidence=True,
            evidence=[EvidenceSource(document_id="d1", chunk_id="c1", quote="예산 산정 근거 인용문", final_score=0.05)],
        )
        result = service.assess_linked_evaluation(linked)
        assert result.status == EvidenceSufficiencyStatus.INSUFFICIENT
        assert result.qualified_evidence_count == 0

    def test_empty_quote_excluded(self):
        service = EvidenceSufficiencyService()
        linked = LinkedEvaluation(
            opinion="예산 근거가 있습니다.",
            has_evidence=True,
            evidence=[EvidenceSource(document_id="d1", chunk_id="c1", quote="", final_score=0.9)],
        )
        result = service.assess_linked_evaluation(linked)
        assert result.status == EvidenceSufficiencyStatus.INSUFFICIENT

    def test_document_id_and_chunk_id_preserved_in_result(self):
        service = EvidenceSufficiencyService()
        linked = LinkedEvaluation(
            opinion="예산 근거가 있습니다.",
            has_evidence=True,
            evidence=[
                EvidenceSource(document_id="d1", chunk_id="c1", quote="예산 산정 근거 인용문", final_score=0.9),
                EvidenceSource(document_id="d1", chunk_id="c2", quote="수익 계획 근거 인용문", final_score=0.85),
            ],
        )
        result = service.assess_linked_evaluation(linked)
        assert result.status == EvidenceSufficiencyStatus.SUFFICIENT
        assert set(result.qualified_document_ids) == {"d1"}
        assert set(result.qualified_chunk_ids) == {"c1", "c2"}

    def test_linked_evaluation_not_mutated(self):
        service = EvidenceSufficiencyService()
        linked = LinkedEvaluation(
            opinion="예산 근거가 있습니다.",
            has_evidence=True,
            evidence=[EvidenceSource(document_id="d1", chunk_id="c1", quote="예산 산정 근거 인용문", final_score=0.9)],
        )
        snapshot = linked.model_dump()
        service.assess_linked_evaluation(linked)
        assert linked.model_dump() == snapshot


class TestLogging:
    def test_start_and_complete_logs_emitted(self, caplog):
        service = EvidenceSufficiencyService()
        with caplog.at_level(logging.INFO, logger="ai.rag.evidence_sufficiency.service"):
            service.assess_search_results([_role_result(final_score=0.9)], role_id="finance", trace_id="trace-1")
        messages = [record.getMessage() for record in caplog.records]
        assert any("[EVIDENCE_SUFFICIENCY_START]" in m for m in messages)
        assert any("[EVIDENCE_SUFFICIENCY_COMPLETE]" in m for m in messages)

    def test_insufficient_warning_log_emitted(self, caplog):
        service = EvidenceSufficiencyService()
        with caplog.at_level(logging.INFO, logger="ai.rag.evidence_sufficiency.service"):
            service.assess_search_results([], role_id="finance", trace_id="trace-2")
        messages = [record.getMessage() for record in caplog.records]
        assert any("[EVIDENCE_INSUFFICIENT]" in m for m in messages)

    def test_logs_do_not_contain_full_content(self, caplog):
        service = EvidenceSufficiencyService()
        secret_content = "이것은 로그에 절대 노출되면 안 되는 민감한 원문 청크 전체 내용입니다."
        with caplog.at_level(logging.INFO, logger="ai.rag.evidence_sufficiency.service"):
            service.assess_search_results(
                [_role_result(content=secret_content, final_score=0.9)],
                role_id="finance",
                trace_id="trace-3",
            )
        messages = [record.getMessage() for record in caplog.records]
        assert not any(secret_content in m for m in messages)
