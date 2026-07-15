"""
Role-Aware Retrieval Service (RAG-003)
==========================================
기존 RAG-002 RAGIndexingService.search()를 재사용해, 심사위원 role_id에 따라
서로 다른 검색 질의를 만들고 결과를 역할 관련도로 재정렬한다. 새 임베딩 모델이나
Chroma client를 만들지 않고, 생성자로 기존 RAGIndexingService 인스턴스를 주입받는다.
"""

from typing import Optional, Protocol

from ai.rag.retrieval.schemas import SearchResult
from ai.rag.role_retrieval.config import RoleRerankConfig
from ai.rag.role_retrieval.query_builder import build_expanded_query
from ai.rag.role_retrieval.reranker import rerank_by_role
from ai.rag.role_retrieval.roles import RoleRegistry
from ai.rag.role_retrieval.schemas import RoleSearchRequest, RoleSearchResponse


class RetrievalServiceLike(Protocol):
    """RAGIndexingService.search()와 동일한 시그니처만 요구하는 최소 인터페이스.
    실제 RAGIndexingService 인스턴스뿐 아니라 테스트용 fake도 그대로 주입할 수 있다."""

    def search(
        self,
        query: str,
        project_id: str,
        document_id: Optional[str] = None,
        top_k: int = 5,
    ) -> list[SearchResult]:
        ...


class RoleAwareRetrievalService:
    def __init__(
        self,
        retrieval_service: RetrievalServiceLike,
        role_registry: Optional[RoleRegistry] = None,
        rerank_config: Optional[RoleRerankConfig] = None,
    ):
        self._retrieval_service = retrieval_service
        self._role_registry = role_registry or RoleRegistry()
        self._rerank_config = rerank_config or RoleRerankConfig()

    def search_by_role(
        self,
        query: str,
        project_id: str,
        role_id: Optional[str] = None,
        document_id: Optional[str] = None,
        top_k: int = 5,
        candidate_k: Optional[int] = None,
    ) -> RoleSearchResponse:
        request = RoleSearchRequest(
            query=query,
            role_id=role_id,
            project_id=project_id,
            document_id=document_id,
            top_k=top_k,
            candidate_k=candidate_k,
        )

        role_profile = None
        if request.role_id is not None:
            # 지원하지 않는 role_id면 RoleRegistry.get()이 UnsupportedRoleError를 던진다.
            role_profile = self._role_registry.get(request.role_id)

        expanded_query = build_expanded_query(request.query, role_profile)

        # RAG-002 검색은 project_id 필터를 내부에서 강제한다 — 여기서도 project_id 없이는 호출하지 않는다.
        candidates: list[SearchResult] = self._retrieval_service.search(
            query=expanded_query,
            project_id=request.project_id,
            document_id=request.document_id,
            top_k=request.candidate_k,
        )

        results = rerank_by_role(
            candidates=candidates,
            role_profile=role_profile,
            role_id=request.role_id,
            config=self._rerank_config,
            top_k=request.top_k,
        )

        return RoleSearchResponse(
            query=request.query,
            expanded_query=expanded_query,
            role_id=request.role_id,
            role_name=role_profile.display_name if role_profile else None,
            project_id=request.project_id,
            document_id=request.document_id,
            results=results,
            result_count=len(results),
            warnings=[],
        )
