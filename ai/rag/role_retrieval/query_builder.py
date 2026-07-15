"""
Role-Aware Query Builder
============================
사용자 질문과 역할 지침(RoleProfile.query_instruction)을 규칙 기반으로 결합해
검색 질의를 만든다. LLM 호출 없음. 원래 사용자 질문은 항상 결과 문자열에 유지된다.
"""

from typing import Optional

from ai.rag.role_retrieval.schemas import RoleProfile


def build_expanded_query(query: str, role_profile: Optional[RoleProfile]) -> str:
    """role_profile이 없으면 원본 질문을 그대로 반환한다 (일반 검색 fallback)."""
    if role_profile is None:
        return query
    return f"{role_profile.query_instruction}\n\n사용자 질문: {query}"
