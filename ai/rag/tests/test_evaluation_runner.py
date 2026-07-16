"""
Unit Tests for ai.rag.evaluation.runner
(FakeRoleSearchRetriever만 사용 — 실제 KURE, Chroma, OpenAI API, LangGraph, MongoDB 없음)
"""

import json

import pytest

from ai.rag.evaluation.runner import RetrievalEvaluationRunner, default_settings_snapshot
from ai.rag.evaluation.schemas import EvaluationCase, EvaluationDataset
from ai.rag.role_retrieval.schemas import RoleSearchResponse, RoleSearchResult


class FakeRoleSearchRetriever:
    """RoleAwareRetrievalService.search_by_role()과 동일한 시그니처를 갖는 mock.
    case_id별로 미리 등록된 RoleSearchResponse만 반환한다."""

    def __init__(self, responses_by_query: dict[str, RoleSearchResponse]):
        self._responses_by_query = responses_by_query
        self.calls: list[dict] = []

    def search_by_role(self, query, project_id, role_id=None, document_id=None, top_k=5, candidate_k=None):
        self.calls.append({
            "query": query,
            "project_id": project_id,
            "role_id": role_id,
            "document_id": document_id,
            "top_k": top_k,
            "candidate_k": candidate_k,
        })
        return self._responses_by_query[query]


def _make_result(chunk_id: str, score: float) -> RoleSearchResult:
    return RoleSearchResult(
        record_id=f"p1::{chunk_id}",
        chunk_id=chunk_id,
        document_id="doc-a",
        content=f"content for {chunk_id}",
        role_score=score,
        final_score=score,
    )


def _make_response(query: str, project_id: str, role_id: str, chunk_ids: list[str]) -> RoleSearchResponse:
    results = [_make_result(cid, 1.0 - i * 0.1) for i, cid in enumerate(chunk_ids)]
    return RoleSearchResponse(
        query=query,
        expanded_query=query,
        role_id=role_id,
        role_name=role_id,
        project_id=project_id,
        results=results,
        result_count=len(results),
    )


def _make_case(case_id="competition-001", query="사업성과 시장 기여도", relevant_chunk_ids=None) -> EvaluationCase:
    return EvaluationCase(
        case_id=case_id,
        project_id="p1",
        domain="competition",
        persona_id="business_strategy",
        role_id="finance",
        criterion_id="contribution",
        query=query,
        relevant_chunk_ids=relevant_chunk_ids or ["c1", "c2"],
    )


def _make_dataset(cases: list[EvaluationCase]) -> EvaluationDataset:
    return EvaluationDataset(dataset_name="test_dataset", version="1.0.0", cases=cases)


class TestArgumentPassthrough:
    def test_query_project_id_role_id_passed_correctly(self):
        case = _make_case()
        response = _make_response(case.query, case.project_id, case.role_id, ["c1", "c2"])
        retriever = FakeRoleSearchRetriever({case.query: response})
        runner = RetrievalEvaluationRunner(retriever=retriever, k_values=[1, 3, 5])

        runner.run(_make_dataset([case]))

        assert retriever.calls[0]["query"] == case.query
        assert retriever.calls[0]["project_id"] == case.project_id
        assert retriever.calls[0]["role_id"] == case.role_id

    def test_top_k_uses_max_of_k_values(self):
        case = _make_case()
        response = _make_response(case.query, case.project_id, case.role_id, ["c1", "c2"])
        retriever = FakeRoleSearchRetriever({case.query: response})
        runner = RetrievalEvaluationRunner(retriever=retriever, k_values=[1, 3, 10])

        runner.run(_make_dataset([case]))

        assert retriever.calls[0]["top_k"] == 10


class TestMultipleKValues:
    def test_each_k_value_produces_its_own_metric(self):
        case = _make_case(relevant_chunk_ids=["c2"])
        response = _make_response(case.query, case.project_id, case.role_id, ["c1", "c2", "c3"])
        retriever = FakeRoleSearchRetriever({case.query: response})
        runner = RetrievalEvaluationRunner(retriever=retriever, k_values=[1, 2, 3])

        report = runner.run(_make_dataset([case]))
        case_metric = report.case_metrics[0]

        assert set(case_metric.precision_at_k.keys()) == {1, 2, 3}
        # c2는 2위이므로 hit_rate@1=0, hit_rate@2=1, hit_rate@3=1
        assert case_metric.hit_rate_at_k[1] == 0.0
        assert case_metric.hit_rate_at_k[2] == 1.0
        assert case_metric.hit_rate_at_k[3] == 1.0


class TestEmptyResultCase:
    def test_case_with_no_results_counted_in_aggregate(self):
        case = _make_case()
        response = _make_response(case.query, case.project_id, case.role_id, [])
        retriever = FakeRoleSearchRetriever({case.query: response})
        runner = RetrievalEvaluationRunner(retriever=retriever, k_values=[1, 3, 5])

        report = runner.run(_make_dataset([case]))

        assert report.aggregate.empty_result_case_count == 1
        assert report.case_metrics[0].reciprocal_rank == 0.0
        assert all(v == 0.0 for v in report.case_metrics[0].precision_at_k.values())


class TestKValueValidation:
    def test_empty_k_values_rejected(self):
        retriever = FakeRoleSearchRetriever({})
        with pytest.raises(ValueError):
            RetrievalEvaluationRunner(retriever=retriever, k_values=[])

    @pytest.mark.parametrize("k_values", [[0], [-1, 3], [1, 0, 5]])
    def test_non_positive_k_rejected(self, k_values):
        retriever = FakeRoleSearchRetriever({})
        with pytest.raises(ValueError):
            RetrievalEvaluationRunner(retriever=retriever, k_values=k_values)


class TestReportSerialization:
    def test_report_is_json_serializable(self):
        case = _make_case()
        response = _make_response(case.query, case.project_id, case.role_id, ["c1", "c2"])
        retriever = FakeRoleSearchRetriever({case.query: response})
        runner = RetrievalEvaluationRunner(retriever=retriever, k_values=[1, 3, 5])

        report = runner.run(_make_dataset([case]))
        dumped = json.loads(report.model_dump_json())

        assert dumped["dataset_name"] == "test_dataset"
        assert dumped["aggregate"]["case_count"] == 1
        assert "1" in dumped["case_metrics"][0]["precision_at_k"]


class TestDefaultSettingsSnapshot:
    def test_reads_values_from_actual_config_not_hardcoded(self):
        from ai.rag.chunking.config import DEFAULT_CHUNK_OVERLAP, DEFAULT_CHUNK_SIZE
        from ai.rag.role_retrieval.config import DEFAULT_ROLE_WEIGHT, DEFAULT_SEMANTIC_WEIGHT

        settings = default_settings_snapshot([1, 3, 5])

        assert settings.chunk_size == DEFAULT_CHUNK_SIZE
        assert settings.chunk_overlap == DEFAULT_CHUNK_OVERLAP
        assert settings.semantic_weight == DEFAULT_SEMANTIC_WEIGHT
        assert settings.role_weight == DEFAULT_ROLE_WEIGHT
        assert settings.k_values == [1, 3, 5]


class TestMultipleCasesAggregate:
    def test_mrr_is_mean_of_reciprocal_ranks(self):
        case1 = _make_case(case_id="c-1", query="q1", relevant_chunk_ids=["c1"])
        case2 = _make_case(case_id="c-2", query="q2", relevant_chunk_ids=["c2"])
        response1 = _make_response("q1", "p1", "finance", ["c1", "c_other"])  # rank 1 -> RR=1.0
        response2 = _make_response("q2", "p1", "finance", ["c_other", "c2"])  # rank 2 -> RR=0.5
        retriever = FakeRoleSearchRetriever({"q1": response1, "q2": response2})
        runner = RetrievalEvaluationRunner(retriever=retriever, k_values=[1, 2])

        report = runner.run(_make_dataset([case1, case2]))

        assert report.aggregate.mrr == pytest.approx(0.75)
        assert report.aggregate.case_count == 2
