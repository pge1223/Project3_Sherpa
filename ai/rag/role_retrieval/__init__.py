"""
Role-Aware Retrieval Module (RAG-003)
=========================================
같은 사용자 질문이라도 심사위원 role_id에 따라 다른 검색 질의를 만들고,
역할 관련도를 반영해 RAG-002 검색 결과를 재정렬한다. LangGraph/FastAPI와
무관하게 단독 실행 가능하며, 내부적으로 기존 RAGIndexingService.search()를 재사용한다.

사용 예시:
    from ai.rag.retrieval import RAGIndexingService  # 기존 RAG-002 서비스
    from ai.rag.role_retrieval import RoleAwareRetrievalService, RoleRegistry

    role_service = RoleAwareRetrievalService(retrieval_service=rag_indexing_service)
    response = role_service.search_by_role(
        query="이 사업의 위험 요소는 무엇인가요?",
        project_id="proj-1",
        role_id="finance",
        top_k=5,
    )
"""

from ai.rag.role_retrieval.config import RoleRerankConfig
from ai.rag.role_retrieval.query_builder import build_expanded_query
from ai.rag.role_retrieval.reranker import combine_scores, compute_role_score, rerank_by_role
from ai.rag.role_retrieval.roles import DEFAULT_ROLE_PROFILES, RoleRegistry, UnsupportedRoleError
from ai.rag.role_retrieval.schemas import RoleProfile, RoleSearchRequest, RoleSearchResponse, RoleSearchResult
from ai.rag.role_retrieval.service import RoleAwareRetrievalService

__all__ = [
    "RoleAwareRetrievalService",
    "RoleRegistry",
    "RoleRerankConfig",
    "RoleProfile",
    "RoleSearchRequest",
    "RoleSearchResult",
    "RoleSearchResponse",
    "UnsupportedRoleError",
    "DEFAULT_ROLE_PROFILES",
    "build_expanded_query",
    "compute_role_score",
    "combine_scores",
    "rerank_by_role",
]
