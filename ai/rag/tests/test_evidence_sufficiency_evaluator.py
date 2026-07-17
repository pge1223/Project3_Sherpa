"""
Unit Tests for ai.rag.evidence_sufficiency.evaluator / config
"""

import math

import pytest
from pydantic import ValidationError

from ai.rag.evidence_linking.schemas import EvidenceSource
from ai.rag.evidence_sufficiency.config import EvidenceSufficiencyConfig
from ai.rag.evidence_sufficiency.evaluator import determine_status, evaluate_candidates
from ai.rag.evidence_sufficiency.schemas import EvidenceReasonCode, EvidenceSufficiencyStatus
from ai.rag.role_retrieval.schemas import RoleSearchResult


def _role_result(
    document_id="d1",
    chunk_id="c1",
    content="예산 세부 계획 설명입니다.",
    final_score=0.8,
    semantic_score=0.5,
    role_score=0.2,
    metadata=None,
) -> RoleSearchResult:
    return RoleSearchResult(
        record_id=chunk_id,
        chunk_id=chunk_id,
        document_id=document_id,
        content=content,
        distance=None,
        semantic_score=semantic_score,
        role_score=role_score,
        final_score=final_score,
        role_id="finance",
        metadata=metadata or {},
    )


def _evidence_source(
    document_id="d1",
    chunk_id="c1",
    quote="예산 세부 계획 설명입니다.",
    final_score=0.8,
) -> EvidenceSource:
    return EvidenceSource(
        document_id=document_id,
        chunk_id=chunk_id,
        quote=quote,
        final_score=final_score,
    )


class TestConfig:
    def test_default_config_creation(self):
        config = EvidenceSufficiencyConfig()
        assert config.min_score == 0.3
        assert config.min_required_evidence == 1
        assert config.preferred_evidence_count == 2

    def test_preferred_must_be_at_least_required(self):
        with pytest.raises(ValidationError):
            EvidenceSufficiencyConfig(min_required_evidence=3, preferred_evidence_count=2)

    def test_preferred_equal_to_required_allowed(self):
        config = EvidenceSufficiencyConfig(min_required_evidence=2, preferred_evidence_count=2)
        assert config.preferred_evidence_count == config.min_required_evidence

    def test_min_score_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            EvidenceSufficiencyConfig(min_score=1.5)
        with pytest.raises(ValidationError):
            EvidenceSufficiencyConfig(min_score=-0.1)

    def test_negative_evidence_count_rejected(self):
        with pytest.raises(ValidationError):
            EvidenceSufficiencyConfig(min_required_evidence=0)
        with pytest.raises(ValidationError):
            EvidenceSufficiencyConfig(preferred_evidence_count=0)

    def test_partial_policy_configurable(self):
        config = EvidenceSufficiencyConfig(
            partial_allows_definitive_judgment=True, partial_allows_numeric_score=True
        )
        assert config.partial_allows_definitive_judgment is True
        assert config.partial_allows_numeric_score is True

    def test_sufficient_numeric_score_policy_configurable(self):
        config = EvidenceSufficiencyConfig(sufficient_allows_numeric_score=False)
        assert config.sufficient_allows_numeric_score is False


class TestStatusDetermination:
    def test_zero_results_insufficient(self):
        config = EvidenceSufficiencyConfig()
        evaluation = evaluate_candidates([], config)
        assert determine_status(len(evaluation.qualified), config) == EvidenceSufficiencyStatus.INSUFFICIENT
        assert EvidenceReasonCode.NO_RESULTS in evaluation.reason_codes

    def test_no_valid_evidence_insufficient(self):
        config = EvidenceSufficiencyConfig()
        results = [_role_result(document_id="", chunk_id="", content="")]
        evaluation = evaluate_candidates(results, config)
        assert determine_status(len(evaluation.qualified), config) == EvidenceSufficiencyStatus.INSUFFICIENT
        assert EvidenceReasonCode.NO_VALID_EVIDENCE in evaluation.reason_codes

    def test_all_below_min_score_insufficient(self):
        config = EvidenceSufficiencyConfig(min_score=0.5)
        results = [_role_result(final_score=0.1), _role_result(chunk_id="c2", final_score=0.2)]
        evaluation = evaluate_candidates(results, config)
        assert len(evaluation.qualified) == 0
        assert EvidenceReasonCode.BELOW_MIN_SCORE in evaluation.reason_codes
        assert determine_status(len(evaluation.qualified), config) == EvidenceSufficiencyStatus.INSUFFICIENT

    def test_below_min_required_count_insufficient(self):
        config = EvidenceSufficiencyConfig(min_required_evidence=2, preferred_evidence_count=3)
        results = [_role_result(final_score=0.9)]
        evaluation = evaluate_candidates(results, config)
        assert len(evaluation.qualified) == 1
        assert determine_status(len(evaluation.qualified), config) == EvidenceSufficiencyStatus.INSUFFICIENT

    def test_min_required_met_but_below_preferred_is_partial(self):
        config = EvidenceSufficiencyConfig(min_required_evidence=1, preferred_evidence_count=2)
        results = [_role_result(final_score=0.9)]
        evaluation = evaluate_candidates(results, config)
        assert len(evaluation.qualified) == 1
        assert determine_status(len(evaluation.qualified), config) == EvidenceSufficiencyStatus.PARTIAL

    def test_at_least_preferred_is_sufficient(self):
        config = EvidenceSufficiencyConfig(min_required_evidence=1, preferred_evidence_count=2)
        results = [
            _role_result(chunk_id="c1", final_score=0.9),
            _role_result(chunk_id="c2", final_score=0.8),
        ]
        evaluation = evaluate_candidates(results, config)
        assert len(evaluation.qualified) == 2
        assert determine_status(len(evaluation.qualified), config) == EvidenceSufficiencyStatus.SUFFICIENT

    def test_preferred_equals_required_boundary(self):
        config = EvidenceSufficiencyConfig(min_required_evidence=1, preferred_evidence_count=1)
        results = [_role_result(final_score=0.9)]
        evaluation = evaluate_candidates(results, config)
        assert determine_status(len(evaluation.qualified), config) == EvidenceSufficiencyStatus.SUFFICIENT

    def test_role_id_not_mutated_by_evaluator(self):
        config = EvidenceSufficiencyConfig()
        results = [_role_result()]
        evaluate_candidates(results, config)
        assert results[0].role_id == "finance"


class TestValidityFiltering:
    def test_empty_content_excluded(self):
        config = EvidenceSufficiencyConfig()
        evaluation = evaluate_candidates([_role_result(content="")], config)
        assert evaluation.valid_count == 0
        assert len(evaluation.qualified) == 0

    def test_whitespace_only_content_excluded(self):
        config = EvidenceSufficiencyConfig()
        evaluation = evaluate_candidates([_role_result(content="   ")], config)
        assert evaluation.valid_count == 0

    def test_short_content_excluded(self):
        config = EvidenceSufficiencyConfig(min_content_length=20)
        evaluation = evaluate_candidates([_role_result(content="짧은 내용")], config)
        assert evaluation.valid_count == 0

    def test_missing_document_id_excluded(self):
        config = EvidenceSufficiencyConfig()
        evaluation = evaluate_candidates([_role_result(document_id="")], config)
        assert evaluation.valid_count == 0
        assert EvidenceReasonCode.MISSING_SOURCE_ID in evaluation.reason_codes

    def test_missing_chunk_id_excluded(self):
        config = EvidenceSufficiencyConfig()
        evaluation = evaluate_candidates([_role_result(chunk_id="")], config)
        assert evaluation.valid_count == 0
        assert EvidenceReasonCode.MISSING_SOURCE_ID in evaluation.reason_codes

    def test_nan_score_excluded(self):
        config = EvidenceSufficiencyConfig()
        result = _role_result(final_score=math.nan)
        evaluation = evaluate_candidates([result], config)
        assert len(evaluation.qualified) == 0

    def test_infinite_score_excluded(self):
        config = EvidenceSufficiencyConfig()
        result = _role_result(final_score=math.inf)
        evaluation = evaluate_candidates([result], config)
        assert len(evaluation.qualified) == 0

    def test_none_score_treated_as_zero_and_excluded(self):
        config = EvidenceSufficiencyConfig(min_score=0.1)

        class _FakeResult:
            document_id = "d1"
            chunk_id = "c1"
            content = "충분히 긴 예산 관련 설명 내용입니다."
            final_score = None
            semantic_score = None
            score = None
            metadata = {}

        evaluation = evaluate_candidates([_FakeResult()], config)
        assert len(evaluation.qualified) == 0

    def test_final_score_priority(self):
        config = EvidenceSufficiencyConfig(min_score=0.0)
        result = _role_result(final_score=0.9, semantic_score=0.1)
        evaluation = evaluate_candidates([result], config)
        assert evaluation.qualified[0].score == 0.9

    def test_semantic_score_fallback(self):
        config = EvidenceSufficiencyConfig(min_score=0.0)

        class _FakeResult:
            document_id = "d1"
            chunk_id = "c1"
            content = "충분히 긴 예산 관련 설명 내용입니다."
            final_score = None
            semantic_score = 0.4
            score = None
            metadata = {}

        evaluation = evaluate_candidates([_FakeResult()], config)
        assert evaluation.qualified[0].score == 0.4

    def test_legacy_score_fallback(self):
        from ai.rag.retrieval.schemas import SearchResult

        config = EvidenceSufficiencyConfig(min_score=0.0)
        result = SearchResult(
            record_id="r1", chunk_id="c1", document_id="d1",
            content="충분히 긴 예산 관련 설명 내용입니다.", score=0.6,
        )
        evaluation = evaluate_candidates([result], config)
        assert evaluation.qualified[0].score == 0.6

    def test_all_scores_missing_defaults_to_zero(self):
        config = EvidenceSufficiencyConfig(min_score=0.0)

        class _FakeResult:
            document_id = "d1"
            chunk_id = "c1"
            content = "충분히 긴 예산 관련 설명 내용입니다."
            final_score = None
            semantic_score = None
            score = None
            metadata = {}

        evaluation = evaluate_candidates([_FakeResult()], config)
        assert evaluation.qualified[0].score == 0.0


class TestDeduplication:
    def test_duplicate_document_and_chunk_deduplicated(self):
        config = EvidenceSufficiencyConfig()
        results = [_role_result(final_score=0.8), _role_result(final_score=0.9)]
        evaluation = evaluate_candidates(results, config)
        assert len(evaluation.qualified) == 1
        assert evaluation.duplicate_count == 1

    def test_same_chunk_id_different_document_not_deduplicated(self):
        config = EvidenceSufficiencyConfig()
        results = [
            _role_result(document_id="d1", chunk_id="c1", final_score=0.8),
            _role_result(document_id="d2", chunk_id="c1", final_score=0.8),
        ]
        evaluation = evaluate_candidates(results, config)
        assert len(evaluation.qualified) == 2
        assert evaluation.duplicate_count == 0

    def test_duplicate_does_not_inflate_qualified_count(self):
        config = EvidenceSufficiencyConfig(min_required_evidence=1, preferred_evidence_count=2)
        results = [_role_result(final_score=0.8) for _ in range(5)]
        evaluation = evaluate_candidates(results, config)
        assert len(evaluation.qualified) == 1
        assert evaluation.duplicate_count == 4

    def test_first_occurrence_kept_in_order(self):
        config = EvidenceSufficiencyConfig()
        results = [
            _role_result(content="첫번째로 등장한 예산 내용입니다.", final_score=0.4),
            _role_result(content="두번째로 등장한 예산 내용입니다.", final_score=0.9),
        ]
        evaluation = evaluate_candidates(results, config)
        assert len(evaluation.qualified) == 1
        # 첫 번째로 등장한 근거를 유지한다 (점수가 더 높은 두 번째로 대체하지 않음).
        assert evaluation.qualified[0].score == 0.4

    def test_duplicate_only_causes_insufficient(self):
        config = EvidenceSufficiencyConfig(min_required_evidence=2, preferred_evidence_count=3)
        results = [_role_result(final_score=0.8) for _ in range(3)]
        evaluation = evaluate_candidates(results, config)
        assert len(evaluation.qualified) == 1
        assert EvidenceReasonCode.DUPLICATE_EVIDENCE_ONLY in evaluation.reason_codes
        assert determine_status(len(evaluation.qualified), config) == EvidenceSufficiencyStatus.INSUFFICIENT


class TestLinkedEvidenceSourceCompatibility:
    def test_evidence_source_accepted_as_candidate(self):
        config = EvidenceSufficiencyConfig()
        evaluation = evaluate_candidates([_evidence_source()], config)
        assert len(evaluation.qualified) == 1

    def test_evidence_source_empty_quote_excluded(self):
        config = EvidenceSufficiencyConfig()
        evaluation = evaluate_candidates([_evidence_source(quote="")], config)
        assert len(evaluation.qualified) == 0

    def test_none_and_empty_input_handled_safely(self):
        config = EvidenceSufficiencyConfig()
        assert evaluate_candidates(None, config).total_count == 0
        assert evaluate_candidates([], config).total_count == 0
