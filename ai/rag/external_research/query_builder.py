"""
Role-Aware External Research Query Builder (RAG-007)
===========================================================
도메인·평가 기준·위원 역할·검색 문맥·지역·자료 유형을 규칙 기반으로 조합해 검색
질의를 만든다. LLM 호출 없음, 순수 함수라 결정론적이다(같은 입력 -> 같은 질의).

역할별 확장 검색어(ROLE_QUERY_TERMS)는 ai.rag.role_retrieval.roles의 위원 역할
ID(finance/technology/marketing/planning)와 동일한 문자열 체계를 쓴다 — 다만 RAG-003의
RoleProfile(내부 문서 근거 검색용 focus_keywords)과는 목적이 달라 그 레지스트리를
재사용하지 않고 이 모듈에서 외부자료 검색 전용 용어 목록을 독립적으로 관리한다.
등록되지 않은 역할이 들어와도 예외를 던지지 않고 확장 검색어 없이 그대로 진행한다
(알 수 없는 역할에 임의의 검색어를 지어내지 않기 위함).
"""

from typing import Optional, Sequence

from ai.rag.external_research.schemas import ExternalEvidenceType

ROLE_QUERY_TERMS: dict[str, list[str]] = {
    "marketing": ["시장 규모", "시장 성장률", "목표 고객", "수요 조사", "경쟁 현황"],
    "planning": ["정책 방향", "지원사업 목적", "사회적 가치", "공공 수요", "제도 적합성"],
    "finance": ["산업 매출", "예산", "비용", "경제 통계", "재정 규모"],
    "technology": ["기술 동향", "도입률", "기술 가이드", "표준", "보안 기준"],
}


def get_role_query_terms(reviewer_role: str) -> list[str]:
    """등록된 역할이면 확장 검색어 목록을, 아니면 빈 리스트를 반환한다(용어를 지어내지 않음)."""
    return list(ROLE_QUERY_TERMS.get(reviewer_role, []))


def build_external_research_query(
    *,
    domain: str,
    evaluation_criteria: Sequence[str],
    reviewer_role: str,
    query_context: Optional[str] = None,
    region: Optional[str] = None,
    evidence_types: Optional[Sequence[ExternalEvidenceType]] = None,
) -> str:
    """도메인/평가 기준/역할/문맥/지역/자료 유형을 조합한 검색 질의를 만든다.
    사용자 입력만으로 구성되며, 이 함수 자체는 통계 수치나 출처를 만들어내지 않는다
    (문자열 조합일 뿐 어떤 사실도 새로 생성하지 않음)."""
    lines = [f"위원 역할: {reviewer_role}", f"도메인: {domain}"]

    role_terms = get_role_query_terms(reviewer_role)
    if role_terms:
        lines.append(f"역할별 관심 주제: {', '.join(role_terms)}")

    lines.append(f"평가 기준: {', '.join(evaluation_criteria)}")

    if query_context:
        lines.append(f"검색 문맥: {query_context}")

    if region:
        lines.append(f"지역: {region}")

    if evidence_types:
        type_names = ", ".join(t.value for t in evidence_types)
        lines.append(f"자료 유형: {type_names}")

    return "\n".join(lines)


__all__ = ["ROLE_QUERY_TERMS", "get_role_query_terms", "build_external_research_query"]
