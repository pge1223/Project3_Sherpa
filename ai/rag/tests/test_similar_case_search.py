"""
Unit Tests for ai.rag.similar_cases.search_service (RAG-006)
==================================================================
실제 chromadb PersistentClient(tmp_path) + FakeCaseEmbedder만 사용한다.
ai.meeting.graph, LangGraph, 실제 LLM API를 import/호출하지 않는다.
"""

import math
from pathlib import Path

import pytest

from ai.rag.retrieval.chroma_store import create_persistent_client
from ai.rag.similar_cases.config import DEFAULT_COLLECTION_NAME, SimilarCaseConfig
from ai.rag.similar_cases.exceptions import SimilarCaseValidationError
from ai.rag.similar_cases.repository import CaseChunkHit, SimilarCaseRepository
from ai.rag.similar_cases.schemas import (
    ComparisonMode,
    SimilarCaseDocument,
    SimilarCaseSearchRequest,
    SimilarCaseType,
)
from ai.rag.similar_cases.search_service import SimilarCaseSearchService, build_similar_case_query
from ai.rag.tests._similar_case_fixtures import FakeCaseEmbedder

_DIM = 4
_UNIT_A = [1.0, 0.0, 0.0, 0.0]
_UNIT_B = [0.0, 1.0, 0.0, 0.0]
_UNIT_C = [0.0, 0.0, 1.0, 0.0]


def _case(case_id="CASE-001", document_id="DOC-001", chunk_id="CHUNK-001", **overrides) -> SimilarCaseDocument:
    base = dict(
        case_id=case_id,
        title="공공데이터 활용 공모전 수상작",
        case_type=SimilarCaseType.AWARD_WINNER,
        domain="public_service",
        evaluation_criteria=["문제 정의", "기술성"],
        source_name="공모전 공식 홈페이지",
        source_url="https://example.org/award/001",
        document_id=document_id,
        chunk_id=chunk_id,
        content="본 서비스는 공공데이터를 활용해 문서를 자동 평가합니다.",
    )
    base.update(overrides)
    return SimilarCaseDocument(**base)


@pytest.fixture
def repository(tmp_path):
    client = create_persistent_client(path=str(tmp_path / "chroma_data"))
    return SimilarCaseRepository(
        client=client,
        collection_name=DEFAULT_COLLECTION_NAME,
        embedding_model="fake-case-embedder",
        embedding_dimension=_DIM,
        embedding_version="embedding_v1",
    )


class TestBuildQuery:
    def test_combines_summary_domain_criteria(self):
        query = build_similar_case_query(
            document_summary="AI 기반 문서 자동 평가 서비스",
            domain="공공서비스 AI",
            evaluation_criteria=["문제 정의", "기술 구현 가능성"],
        )
        assert "도메인: 공공서비스 AI" in query
        assert "문제 정의, 기술 구현 가능성" in query
        assert "AI 기반 문서 자동 평가 서비스" in query

    def test_does_not_silently_truncate_summary(self):
        long_summary = "매우 긴 문서 요약. " * 50
        query = build_similar_case_query(document_summary=long_summary, domain="d", evaluation_criteria=["c"])
        assert long_summary in query


class TestRequestValidation:
    def test_blank_summary_rejected(self):
        with pytest.raises(SimilarCaseValidationError):
            SimilarCaseSearchRequest(document_summary="  ", domain="d", evaluation_criteria=["c"])

    def test_blank_domain_rejected(self):
        with pytest.raises(SimilarCaseValidationError):
            SimilarCaseSearchRequest(document_summary="요약", domain=" ", evaluation_criteria=["c"])

    def test_empty_criteria_rejected(self):
        with pytest.raises(SimilarCaseValidationError):
            SimilarCaseSearchRequest(document_summary="요약", domain="d", evaluation_criteria=[])

    def test_blank_criteria_entry_rejected(self):
        with pytest.raises(SimilarCaseValidationError):
            SimilarCaseSearchRequest(document_summary="요약", domain="d", evaluation_criteria=["ok", "  "])

    def test_zero_top_k_rejected(self):
        with pytest.raises(SimilarCaseValidationError):
            SimilarCaseSearchRequest(document_summary="요약", domain="d", evaluation_criteria=["c"], top_k=0)

    def test_negative_top_k_rejected(self):
        with pytest.raises(SimilarCaseValidationError):
            SimilarCaseSearchRequest(document_summary="요약", domain="d", evaluation_criteria=["c"], top_k=-1)

    def test_excessive_top_k_rejected(self):
        with pytest.raises(SimilarCaseValidationError):
            SimilarCaseSearchRequest(document_summary="요약", domain="d", evaluation_criteria=["c"], top_k=10_000)

    def test_nan_min_score_rejected(self):
        with pytest.raises(SimilarCaseValidationError):
            SimilarCaseSearchRequest(
                document_summary="요약", domain="d", evaluation_criteria=["c"], min_score=math.nan
            )

    def test_infinite_min_score_rejected(self):
        with pytest.raises(SimilarCaseValidationError):
            SimilarCaseSearchRequest(
                document_summary="요약", domain="d", evaluation_criteria=["c"], min_score=math.inf
            )

    def test_valid_request_constructed(self):
        request = SimilarCaseSearchRequest(document_summary="요약", domain="d", evaluation_criteria=["c"])
        assert request.top_k == 5


class TestFilterAndDedupe:
    def _hit(self, document_id, chunk_id, score) -> CaseChunkHit:
        return CaseChunkHit(
            record_id=f"{document_id}::{chunk_id}",
            document_id=document_id,
            chunk_id=chunk_id,
            content="내용",
            distance=None if score is None else 1.0 - score,
            score=score,
            metadata={"case_id": "CASE-X", "source_name": "s", "source_url": "https://x"},
        )

    def test_nan_score_excluded(self):
        hits = [self._hit("d1", "c1", math.nan)]
        result = SimilarCaseSearchService._filter_and_dedupe(hits, min_score=0.0)
        assert result == []

    def test_infinite_score_excluded(self):
        hits = [self._hit("d1", "c1", math.inf)]
        result = SimilarCaseSearchService._filter_and_dedupe(hits, min_score=0.0)
        assert result == []

    def test_none_score_excluded(self):
        hits = [self._hit("d1", "c1", None)]
        result = SimilarCaseSearchService._filter_and_dedupe(hits, min_score=0.0)
        assert result == []

    def test_below_min_score_excluded(self):
        hits = [self._hit("d1", "c1", 0.2)]
        result = SimilarCaseSearchService._filter_and_dedupe(hits, min_score=0.5)
        assert result == []

    def test_duplicate_document_and_chunk_id_deduplicated(self):
        hits = [self._hit("d1", "c1", 0.9), self._hit("d1", "c1", 0.8)]
        result = SimilarCaseSearchService._filter_and_dedupe(hits, min_score=0.0)
        assert len(result) == 1
        assert result[0].score == 0.9  # 첫 번째(더 높은 원본 검색 순서) 유지


class TestAggregateBySource:
    def _hit(self, case_id, document_id, chunk_id, score, source_name="s", source_url="https://x") -> CaseChunkHit:
        return CaseChunkHit(
            record_id=f"{document_id}::{chunk_id}",
            document_id=document_id,
            chunk_id=chunk_id,
            content="내용",
            distance=1.0 - score,
            score=score,
            metadata={"case_id": case_id, "source_name": source_name, "source_url": source_url},
        )

    def test_case_without_source_excluded_with_warning(self):
        hits = [self._hit("CASE-1", "d1", "c1", 0.9, source_name="", source_url="")]
        warnings: list[str] = []
        accumulators = SimilarCaseSearchService._aggregate_by_case(hits, warnings)
        assert accumulators == {}
        assert any("출처 정보가 없는 사례" in w for w in warnings)

    def test_case_with_source_included(self):
        hits = [self._hit("CASE-1", "d1", "c1", 0.9)]
        warnings: list[str] = []
        accumulators = SimilarCaseSearchService._aggregate_by_case(hits, warnings)
        assert "CASE-1" in accumulators
        assert warnings == []


class TestSearchEndToEnd:
    def test_top_k_applied(self, repository):
        embedder = FakeCaseEmbedder(dimension=_DIM, overrides={
            "query": _UNIT_A,
            "case A content": _UNIT_A,
            "case B content": _UNIT_A,
            "case C content": _UNIT_A,
        })
        for i, text in enumerate(["case A content", "case B content", "case C content"]):
            case = _case(case_id=f"CASE-{i}", document_id=f"DOC-{i}", content=text)
            repository.upsert_case_chunk(case, embedder.embed_query(text))

        service = SimilarCaseSearchService(repository, embedder)
        # build_similar_case_query 결과를 그대로 override key로 등록해야 하므로,
        # 질의 텍스트를 미리 계산해 override에 추가한다.
        query_text = build_similar_case_query(document_summary="s", domain="d", evaluation_criteria=["c"])
        embedder._overrides[query_text] = _UNIT_A

        response = service.search(
            SimilarCaseSearchRequest(document_summary="s", domain="d", evaluation_criteria=["c"], top_k=2)
        )
        assert len(response.results) == 2
        assert response.total_results == 2

    def test_min_score_applied(self, repository):
        query_text = build_similar_case_query(document_summary="s", domain="d", evaluation_criteria=["c"])
        embedder = FakeCaseEmbedder(dimension=_DIM, overrides={
            query_text: _UNIT_A,
            "close": _UNIT_A,       # score ~1.0
            "far": _UNIT_B,         # score ~0.0 (직교)
        })
        repository.upsert_case_chunk(_case(case_id="CASE-close", document_id="d-close", content="close"), _UNIT_A)
        repository.upsert_case_chunk(_case(case_id="CASE-far", document_id="d-far", content="far"), _UNIT_B)

        service = SimilarCaseSearchService(repository, embedder, config=SimilarCaseConfig(min_score=0.5))
        response = service.search(
            SimilarCaseSearchRequest(document_summary="s", domain="d", evaluation_criteria=["c"], top_k=5)
        )
        assert len(response.results) == 1
        assert response.results[0].case_id == "CASE-close"

    def test_domain_filter_applied(self, repository):
        query_text = build_similar_case_query(document_summary="s", domain="finance", evaluation_criteria=["c"])
        embedder = FakeCaseEmbedder(dimension=_DIM, overrides={
            query_text: _UNIT_A,
            "finance content": _UNIT_A,
            "public content": _UNIT_A,
        })
        repository.upsert_case_chunk(
            _case(case_id="CASE-fin", document_id="d-fin", domain="finance", content="finance content"), _UNIT_A
        )
        repository.upsert_case_chunk(
            _case(case_id="CASE-pub", document_id="d-pub", domain="public_service", content="public content"),
            _UNIT_A,
        )

        service = SimilarCaseSearchService(repository, embedder)
        response = service.search(
            SimilarCaseSearchRequest(document_summary="s", domain="finance", evaluation_criteria=["c"], top_k=5)
        )
        assert len(response.results) == 1
        assert response.results[0].case_id == "CASE-fin"

    def test_domain_filter_falls_back_to_all_when_empty(self, repository):
        query_text = build_similar_case_query(document_summary="s", domain="nonexistent", evaluation_criteria=["c"])
        embedder = FakeCaseEmbedder(dimension=_DIM, overrides={query_text: _UNIT_A, "content": _UNIT_A})
        repository.upsert_case_chunk(
            _case(case_id="CASE-1", document_id="d-1", domain="public_service", content="content"), _UNIT_A
        )

        service = SimilarCaseSearchService(
            repository, embedder, config=SimilarCaseConfig(domain_filter_fallback_to_all=True)
        )
        response = service.search(
            SimilarCaseSearchRequest(document_summary="s", domain="nonexistent", evaluation_criteria=["c"], top_k=5)
        )
        assert len(response.results) == 1
        assert any("전체 사례에서 검색했습니다" in w for w in response.warnings)

    def test_domain_filter_no_fallback_returns_empty(self, repository):
        query_text = build_similar_case_query(document_summary="s", domain="nonexistent", evaluation_criteria=["c"])
        embedder = FakeCaseEmbedder(dimension=_DIM, overrides={query_text: _UNIT_A, "content": _UNIT_A})
        repository.upsert_case_chunk(
            _case(case_id="CASE-1", document_id="d-1", domain="public_service", content="content"), _UNIT_A
        )

        service = SimilarCaseSearchService(
            repository, embedder, config=SimilarCaseConfig(domain_filter_fallback_to_all=False)
        )
        response = service.search(
            SimilarCaseSearchRequest(document_summary="s", domain="nonexistent", evaluation_criteria=["c"], top_k=5)
        )
        assert response.results == []

    def test_multiple_chunks_of_same_case_aggregated_into_one_result(self, repository):
        query_text = build_similar_case_query(document_summary="s", domain="d", evaluation_criteria=["c"])
        embedder = FakeCaseEmbedder(dimension=_DIM, overrides={
            query_text: _UNIT_A,
            "chunk one": _UNIT_A,
            "chunk two": _UNIT_A,
        })
        repository.upsert_case_chunk(
            _case(case_id="CASE-1", document_id="d-1", chunk_id="c1", content="chunk one"), _UNIT_A
        )
        repository.upsert_case_chunk(
            _case(case_id="CASE-1", document_id="d-1", chunk_id="c2", content="chunk two"), _UNIT_A
        )

        service = SimilarCaseSearchService(repository, embedder)
        response = service.search(
            SimilarCaseSearchRequest(document_summary="s", domain="d", evaluation_criteria=["c"], top_k=5)
        )
        assert len(response.results) == 1
        assert len(response.results[0].evidence) == 2

    def test_results_sorted_by_similarity_score_descending(self, repository):
        query_text = build_similar_case_query(document_summary="s", domain="d", evaluation_criteria=["c"])
        embedder = FakeCaseEmbedder(dimension=_DIM, overrides={
            query_text: _UNIT_A,
            "medium match": [0.7, 0.7141, 0.0, 0.0],
            "best match": _UNIT_A,
        })
        repository.upsert_case_chunk(
            _case(case_id="CASE-medium", document_id="d-medium", content="medium match"),
            embedder.embed_query("medium match"),
        )
        repository.upsert_case_chunk(
            _case(case_id="CASE-best", document_id="d-best", content="best match"), _UNIT_A
        )

        service = SimilarCaseSearchService(repository, embedder)
        response = service.search(
            SimilarCaseSearchRequest(document_summary="s", domain="d", evaluation_criteria=["c"], top_k=5)
        )
        scores = [r.similarity_score for r in response.results]
        assert scores == sorted(scores, reverse=True)
        assert response.results[0].case_id == "CASE-best"

    def test_no_results_returns_empty_list_not_error(self, repository):
        query_text = build_similar_case_query(document_summary="s", domain="d", evaluation_criteria=["c"])
        embedder = FakeCaseEmbedder(dimension=_DIM, overrides={query_text: _UNIT_A})

        service = SimilarCaseSearchService(repository, embedder)
        response = service.search(
            SimilarCaseSearchRequest(document_summary="s", domain="d", evaluation_criteria=["c"], top_k=5)
        )
        assert response.results == []
        assert response.total_results == 0
        assert any("찾지 못했습니다" in w for w in response.warnings)

    def test_no_fabricated_cases_results_match_indexed_data_exactly(self, repository):
        query_text = build_similar_case_query(document_summary="s", domain="d", evaluation_criteria=["c"])
        embedder = FakeCaseEmbedder(dimension=_DIM, overrides={query_text: _UNIT_A, "real content": _UNIT_A})
        indexed_case = _case(case_id="CASE-REAL", document_id="d-real", content="real content")
        repository.upsert_case_chunk(indexed_case, _UNIT_A)

        service = SimilarCaseSearchService(repository, embedder)
        response = service.search(
            SimilarCaseSearchRequest(document_summary="s", domain="d", evaluation_criteria=["c"], top_k=5)
        )
        assert len(response.results) == 1
        result = response.results[0]
        assert result.case_id == indexed_case.case_id
        assert result.source_url == indexed_case.source_url
        assert result.evidence[0].quote == indexed_case.content

    def test_reference_only_always_true(self, repository):
        query_text = build_similar_case_query(document_summary="s", domain="d", evaluation_criteria=["c"])
        embedder = FakeCaseEmbedder(dimension=_DIM, overrides={query_text: _UNIT_A, "content": _UNIT_A})
        repository.upsert_case_chunk(_case(content="content"), _UNIT_A)

        service = SimilarCaseSearchService(repository, embedder)
        response = service.search(
            SimilarCaseSearchRequest(document_summary="s", domain="d", evaluation_criteria=["c"], top_k=5)
        )
        assert response.reference_only is True
        assert response.results[0].reference_only is True

    def test_no_rejected_cases_sets_selected_case_gap_mode(self, repository):
        query_text = build_similar_case_query(document_summary="s", domain="d", evaluation_criteria=["c"])
        embedder = FakeCaseEmbedder(dimension=_DIM, overrides={query_text: _UNIT_A, "content": _UNIT_A})
        repository.upsert_case_chunk(_case(content="content", case_type=SimilarCaseType.AWARD_WINNER), _UNIT_A)

        service = SimilarCaseSearchService(repository, embedder)
        response = service.search(
            SimilarCaseSearchRequest(document_summary="s", domain="d", evaluation_criteria=["c"], top_k=5)
        )
        assert response.has_rejected_cases is False
        assert response.comparison_mode == ComparisonMode.SELECTED_CASE_GAP
        assert any("탈락 사례 데이터가 없어" in w for w in response.warnings)

    def test_rejected_case_present_sets_selected_and_rejected_mode(self, repository):
        query_text = build_similar_case_query(document_summary="s", domain="d", evaluation_criteria=["c"])
        embedder = FakeCaseEmbedder(dimension=_DIM, overrides={query_text: _UNIT_A, "content": _UNIT_A})
        repository.upsert_case_chunk(
            _case(content="content", case_type=SimilarCaseType.REJECTED_CASE), _UNIT_A
        )

        service = SimilarCaseSearchService(repository, embedder)
        response = service.search(
            SimilarCaseSearchRequest(document_summary="s", domain="d", evaluation_criteria=["c"], top_k=5)
        )
        assert response.has_rejected_cases is True
        assert response.comparison_mode == ComparisonMode.SELECTED_AND_REJECTED_CASES
        assert not any("탈락 사례 데이터가 없어" in w for w in response.warnings)


class TestIndependentExecution:
    """LangGraph/ai.meeting.graph 없이 단독 실행 가능함을 정적으로 확인한다."""

    def test_package_source_does_not_import_meeting_graph_or_langgraph(self):
        """실제 import 구문만 검사한다 — comparison_service.py의 설계 의도를 설명하는
        docstring/주석에는 "ai.meeting.graph"라는 문자열이 (import하지 않는다는 설명으로)
        등장하므로 단순 부분 문자열 검색은 오탐을 일으킨다."""
        package_dir = Path(__file__).parent.parent / "similar_cases"
        forbidden_prefixes = ("import ai.meeting", "from ai.meeting", "import langgraph", "from langgraph")
        offenders = []
        for py_file in package_dir.glob("*.py"):
            for line in py_file.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped.startswith(forbidden_prefixes):
                    offenders.append((py_file.name, stripped))
        assert offenders == []

    def test_service_constructible_without_langgraph_installed_check(self, repository):
        embedder = FakeCaseEmbedder(dimension=_DIM)
        # 생성자 호출 자체가 LangGraph/ai.meeting.graph를 필요로 하지 않음을 확인.
        service = SimilarCaseSearchService(repository, embedder)
        assert service is not None
