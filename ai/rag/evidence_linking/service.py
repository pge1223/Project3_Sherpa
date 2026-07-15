"""
Evidence Linking Service (RAG-004)
======================================
LangGraph 위원 노드가 평가 의견 하나와 (역할 기반) 검색 결과를 받아 근거 출처를
연결할 때 쓰는 공개 인터페이스. 새 임베딩 모델이나 Chroma client를 만들지 않고,
필요하면 기존 검색 서비스(RAGIndexingService 또는 RoleAwareRetrievalService)를
생성자 주입으로 재사용한다.
"""

from typing import Any, Optional, Protocol

from ai.rag.evidence_linking.config import EvidenceLinkingConfig
from ai.rag.evidence_linking.linker import build_linked_evaluation
from ai.rag.evidence_linking.schemas import LinkedEvaluation


class SearchServiceLike(Protocol):
    """RAGIndexingService.search()와 동일한 시그니처만 요구하는 최소 인터페이스."""

    def search(
        self,
        query: str,
        project_id: str,
        document_id: Optional[str] = None,
        top_k: int = 5,
    ) -> list[Any]:
        ...


class RoleRegistryLike(Protocol):
    """ai.rag.role_retrieval.RoleRegistry와 동일한 최소 인터페이스 (role_keywords 조회용)."""

    def has(self, role_id: str) -> bool:
        ...

    def get(self, role_id: str) -> Any:
        ...


class EvidenceLinkingService:
    def __init__(
        self,
        retrieval_service: Optional[SearchServiceLike] = None,
        config: Optional[EvidenceLinkingConfig] = None,
        role_registry: Optional[RoleRegistryLike] = None,
    ):
        self._retrieval_service = retrieval_service
        self._config = config or EvidenceLinkingConfig()
        self._role_registry = role_registry

    def link_evidence(
        self,
        opinion: str,
        search_results: list[Any],
        role_id: Optional[str] = None,
        role_name: Optional[str] = None,
        max_evidence: Optional[int] = None,
    ) -> LinkedEvaluation:
        """이미 확보한 검색 결과(RAG-002 SearchResult 또는 RAG-003 RoleSearchResult)로 근거를 연결한다.
        새 검색을 수행하지 않는다."""
        return build_linked_evaluation(
            opinion=opinion,
            search_results=search_results,
            config=self._config,
            role_id=role_id,
            role_name=role_name,
            role_keywords=self._resolve_role_keywords(role_id),
            max_evidence=max_evidence,
        )

    def search_and_link(
        self,
        opinion: str,
        query: str,
        project_id: str,
        role_id: Optional[str] = None,
        role_name: Optional[str] = None,
        document_id: Optional[str] = None,
        top_k: int = 5,
        max_evidence: Optional[int] = None,
    ) -> LinkedEvaluation:
        """주입된 검색 서비스로 검색까지 수행한 뒤 근거를 연결한다.
        project_id/document_id는 검색 서비스에 그대로 전달되며, 그 외 별도 조회는 하지 않는다."""
        if self._retrieval_service is None:
            raise ValueError("search_and_link()를 사용하려면 retrieval_service를 주입해야 합니다")
        if not query or not query.strip():
            raise ValueError("query는 빈 문자열일 수 없습니다")
        if not project_id or not project_id.strip():
            raise ValueError("project_id는 빈 문자열일 수 없습니다")

        search_results = self._retrieval_service.search(
            query=query,
            project_id=project_id,
            document_id=document_id,
            top_k=top_k,
        )
        return self.link_evidence(
            opinion=opinion,
            search_results=search_results,
            role_id=role_id,
            role_name=role_name,
            max_evidence=max_evidence,
        )

    def _resolve_role_keywords(self, role_id: Optional[str]) -> Optional[list[str]]:
        if role_id is None or self._role_registry is None:
            return None
        if not self._role_registry.has(role_id):
            return None
        return self._role_registry.get(role_id).focus_keywords
