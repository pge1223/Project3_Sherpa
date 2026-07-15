"""
Unit Tests for ai.rag.evidence_linking.service.EvidenceLinkingService
(mock retrieval service만 사용 — 실제 KURE-v1/Chroma 없음)
"""

import pytest

from ai.rag.evidence_linking.config import EvidenceLinkingConfig
from ai.rag.evidence_linking.service import EvidenceLinkingService
from ai.rag.retrieval.schemas import SearchResult
from ai.rag.role_retrieval.roles import RoleRegistry


class FakeRetrievalService:
    """RAGIndexingService.search()와 동일한 시그니처의 mock. 새 Chroma client를 만들지 않고,
    project_id별로 등록된 결과만 반환해 project 격리를 시뮬레이션한다."""

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


def _result(record_id, document_id, content, score, section_title=None) -> SearchResult:
    return SearchResult(
        record_id=record_id,
        chunk_id=record_id,
        document_id=document_id,
        content=content,
        distance=1.0 - score,
        score=score,
        metadata={"section_title": section_title},
    )


class TestLinkEvidence:
    def test_link_evidence_without_retrieval_service(self):
        service = EvidenceLinkingService()
        results = [_result("c1", "d1", "총사업비는 5,000만 원으로 산정하였다.", score=0.9, section_title="사업비 구성")]
        linked = service.link_evidence(
            opinion="예산 산정 기준과 세부 사용 계획이 부족합니다.",
            search_results=results,
        )
        assert linked.has_evidence is True
        assert linked.evidence[0].section_title == "사업비 구성"

    def test_role_keywords_used_when_registry_provided(self):
        # opinion 자체는 두 문장 모두와 공통 키워드가 없어, role_keywords가 있어야만
        # 재무 관련 문장이 인용문으로 선택된다.
        service = EvidenceLinkingService(role_registry=RoleRegistry())
        results = [
            _result(
                "c1", "d1",
                "고객 응대 방법에 대한 일반 설명이다. 예산 및 자금조달, 재무 위험에 대한 설명이다.",
                score=0.9,
            ),
        ]
        linked = service.link_evidence(
            opinion="이 사업의 전반적인 완성도를 평가해주세요.",
            search_results=results,
            role_id="finance",
            role_name="재무 심사위원",
        )
        assert linked.role_id == "finance"
        assert "예산" in linked.evidence[0].quote or "자금조달" in linked.evidence[0].quote


class TestSearchAndLink:
    def test_project_id_passed_to_retrieval_service(self):
        fake = FakeRetrievalService({"p1": [_result("c1", "d1", "예산 세부 계획 설명", score=0.9)]})
        service = EvidenceLinkingService(retrieval_service=fake)
        service.search_and_link(opinion="예산 근거가 부족합니다.", query="예산은?", project_id="p1")
        assert fake.calls[0]["project_id"] == "p1"

    def test_document_id_passed_to_retrieval_service(self):
        fake = FakeRetrievalService({"p1": [_result("c1", "d1", "예산 세부 계획 설명", score=0.9)]})
        service = EvidenceLinkingService(retrieval_service=fake)
        service.search_and_link(opinion="예산 근거가 부족합니다.", query="예산은?", project_id="p1", document_id="d1")
        assert fake.calls[0]["document_id"] == "d1"

    def test_no_data_beyond_single_search_call(self):
        fake = FakeRetrievalService({"p1": [_result("c1", "d1", "예산 세부 계획 설명", score=0.9)]})
        service = EvidenceLinkingService(retrieval_service=fake)
        service.search_and_link(opinion="예산 근거가 부족합니다.", query="예산은?", project_id="p1")
        assert len(fake.calls) == 1

    def test_other_project_results_never_merged(self):
        fake = FakeRetrievalService({
            "p1": [_result("c1", "d1", "예산 세부 계획 설명", score=0.9)],
            "p2": [_result("c2", "d2", "다른 프로젝트 예산 설명", score=0.9)],
        })
        service = EvidenceLinkingService(retrieval_service=fake)
        linked = service.search_and_link(opinion="예산 근거가 부족합니다.", query="예산은?", project_id="p1")
        assert all(e.document_id == "d1" for e in linked.evidence)

    def test_empty_project_id_rejected(self):
        fake = FakeRetrievalService({"p1": []})
        service = EvidenceLinkingService(retrieval_service=fake)
        with pytest.raises(ValueError):
            service.search_and_link(opinion="의견", query="질문", project_id="")

    def test_empty_query_rejected(self):
        fake = FakeRetrievalService({"p1": []})
        service = EvidenceLinkingService(retrieval_service=fake)
        with pytest.raises(ValueError):
            service.search_and_link(opinion="의견", query="", project_id="p1")

    def test_search_and_link_without_retrieval_service_raises(self):
        service = EvidenceLinkingService()
        with pytest.raises(ValueError):
            service.search_and_link(opinion="의견", query="질문", project_id="p1")

    def test_max_evidence_respected(self):
        fake = FakeRetrievalService({
            "p1": [_result(f"c{i}", "d1", "예산 세부 계획 설명", score=0.9 - i * 0.01) for i in range(5)],
        })
        service = EvidenceLinkingService(retrieval_service=fake, config=EvidenceLinkingConfig())
        linked = service.search_and_link(opinion="예산 근거가 부족합니다.", query="예산은?", project_id="p1", max_evidence=2)
        assert len(linked.evidence) == 2

    def test_no_evidence_when_below_min_score(self):
        fake = FakeRetrievalService({"p1": [_result("c1", "d1", "예산 세부 계획 설명", score=0.05)]})
        service = EvidenceLinkingService(retrieval_service=fake, config=EvidenceLinkingConfig(min_evidence_score=0.3))
        linked = service.search_and_link(opinion="예산 근거가 부족합니다.", query="예산은?", project_id="p1")
        assert linked.has_evidence is False
