"""
Unit Tests for ai.rag.role_retrieval.service.RoleAwareRetrievalService
(mock retrieval service만 사용 — 실제 KURE-v1/Chroma 없음)
"""

import pytest
from pydantic import ValidationError

from ai.rag.retrieval.schemas import SearchResult
from ai.rag.role_retrieval.roles import RoleRegistry, UnsupportedRoleError
from ai.rag.role_retrieval.service import RoleAwareRetrievalService


class FakeRetrievalService:
    """RAGIndexingService.search()와 동일한 시그니처를 갖는 mock.
    project_id별로 미리 등록된 SearchResult만 반환해 project 격리를 시뮬레이션한다."""

    def __init__(self, records_by_project: dict[str, list[SearchResult]]):
        self._records_by_project = records_by_project
        self.calls: list[dict] = []

    def search(self, query, project_id, document_id=None, top_k=5):
        self.calls.append({
            "query": query,
            "project_id": project_id,
            "document_id": document_id,
            "top_k": top_k,
        })
        results = list(self._records_by_project.get(project_id, []))
        if document_id is not None:
            results = [r for r in results if r.document_id == document_id]
        return results[:top_k]


def _make_result(record_id, document_id, content, score, section_title=None, document_title=None) -> SearchResult:
    return SearchResult(
        record_id=record_id,
        chunk_id=record_id,
        document_id=document_id,
        content=content,
        distance=1.0 - score,
        score=score,
        metadata={"section_title": section_title, "document_title": document_title, "content_kind": "body"},
    )


def _p1_records() -> list[SearchResult]:
    return [
        _make_result("p1::r1", "doc-a", "예산과 자금조달, 재무 위험에 대한 설명", 0.6, section_title="예산 계획"),
        _make_result("p1::r2", "doc-a", "기술 구조와 보안, 확장성에 대한 설명", 0.6, section_title="기술 아키텍처"),
        _make_result("p1::r3", "doc-b", "일반적인 사업 개요 설명", 0.55),
    ]


def _p2_records() -> list[SearchResult]:
    return [_make_result("p2::r1", "doc-c", "다른 프로젝트의 문서 내용", 0.9)]


def _make_service(fake: FakeRetrievalService) -> RoleAwareRetrievalService:
    return RoleAwareRetrievalService(retrieval_service=fake, role_registry=RoleRegistry())


class TestValidation:
    def test_unsupported_role_id_raises(self):
        fake = FakeRetrievalService({"p1": _p1_records()})
        service = _make_service(fake)
        with pytest.raises(UnsupportedRoleError):
            service.search_by_role(query="위험 요소는?", project_id="p1", role_id="legal")

    def test_empty_query_rejected(self):
        fake = FakeRetrievalService({"p1": _p1_records()})
        service = _make_service(fake)
        with pytest.raises(ValidationError):
            service.search_by_role(query="", project_id="p1")

    def test_empty_project_id_rejected(self):
        fake = FakeRetrievalService({"p1": _p1_records()})
        service = _make_service(fake)
        with pytest.raises(ValidationError):
            service.search_by_role(query="위험 요소는?", project_id="")

    def test_candidate_k_defaults_to_at_least_top_k(self):
        fake = FakeRetrievalService({"p1": _p1_records()})
        service = _make_service(fake)
        service.search_by_role(query="위험 요소는?", project_id="p1", top_k=5)
        assert fake.calls[0]["top_k"] >= 5


class TestFallback:
    def test_role_id_none_uses_plain_search(self):
        fake = FakeRetrievalService({"p1": _p1_records()})
        service = _make_service(fake)
        response = service.search_by_role(query="위험 요소는?", project_id="p1")
        assert response.role_id is None
        assert response.role_name is None
        assert response.expanded_query == response.query


class TestArgumentPassthrough:
    def test_project_id_passed_correctly(self):
        fake = FakeRetrievalService({"p1": _p1_records()})
        service = _make_service(fake)
        service.search_by_role(query="위험 요소는?", project_id="p1", role_id="finance")
        assert fake.calls[0]["project_id"] == "p1"

    def test_document_id_passed_correctly(self):
        fake = FakeRetrievalService({"p1": _p1_records()})
        service = _make_service(fake)
        service.search_by_role(query="위험 요소는?", project_id="p1", document_id="doc-a", role_id="finance")
        assert fake.calls[0]["document_id"] == "doc-a"

    def test_candidate_k_used_for_underlying_search(self):
        fake = FakeRetrievalService({"p1": _p1_records()})
        service = _make_service(fake)
        service.search_by_role(query="위험 요소는?", project_id="p1", top_k=2, candidate_k=6)
        assert fake.calls[0]["top_k"] == 6

    def test_final_results_at_most_top_k(self):
        fake = FakeRetrievalService({"p1": _p1_records()})
        service = _make_service(fake)
        response = service.search_by_role(query="위험 요소는?", project_id="p1", top_k=1, candidate_k=10)
        assert len(response.results) <= 1


class TestProjectIsolation:
    def test_other_project_results_never_returned(self):
        fake = FakeRetrievalService({"p1": _p1_records(), "p2": _p2_records()})
        service = _make_service(fake)
        response = service.search_by_role(query="위험 요소는?", project_id="p1", role_id="finance", top_k=10)
        assert all(r.record_id.startswith("p1::") for r in response.results)
        assert fake.calls[0]["project_id"] == "p1"


class TestRoleDifferentiation:
    def test_finance_and_technology_produce_different_order(self):
        fake = FakeRetrievalService({"p1": _p1_records()})
        service = _make_service(fake)

        finance_response = service.search_by_role(query="이 사업의 강점은?", project_id="p1", role_id="finance", top_k=3)
        technology_response = service.search_by_role(
            query="이 사업의 강점은?", project_id="p1", role_id="technology", top_k=3
        )

        finance_order = [r.chunk_id for r in finance_response.results]
        technology_order = [r.chunk_id for r in technology_response.results]
        assert finance_order != technology_order
        assert finance_response.expanded_query != technology_response.expanded_query

    def test_no_embedding_vector_in_response(self):
        fake = FakeRetrievalService({"p1": _p1_records()})
        service = _make_service(fake)
        response = service.search_by_role(query="위험 요소는?", project_id="p1", role_id="finance")
        dumped = response.model_dump()
        assert "embedding" not in str(dumped.keys())
        for result in response.results:
            assert "embedding" not in result.model_dump()

    def test_original_content_and_source_metadata_preserved(self):
        fake = FakeRetrievalService({"p1": _p1_records()})
        service = _make_service(fake)
        response = service.search_by_role(query="위험 요소는?", project_id="p1", role_id="finance")
        matched = [r for r in response.results if r.chunk_id == "p1::r1"][0]
        assert "예산과 자금조달" in matched.content
        assert matched.metadata["section_title"] == "예산 계획"
