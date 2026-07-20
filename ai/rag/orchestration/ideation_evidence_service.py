"""
Ideation Evidence Service
=============================
용준/Claude(2026-07-20). "아이디어 발전 회의(ideation)" 전문가(planning_expert/dev_expert)에게
넘길 근거를 검색한다.

기존 MeetingEvidenceOrchestrationService(meeting_evidence_service.py)는 (persona_id,
criterion_id) 단위로 동작하는데, ideation 모드에는 rubric criterion 개념이 없다 — 채점 기준별로
배정되는 게 아니라 공모전 공고·평가기준과 사용자 아이디어를 놓고 대화할 뿐이다. 그래서 이 모듈은
criterion 단위 오케스트레이션(사전 근거충족도 판정, RAG-004 사후 링크)을 그대로 가져다 쓰지 않고,
더 가벼운 함수 하나로 persona_id -> 고정 role_id 매핑만 하고 RoleAwareRetrievalService.
search_by_role()을 직접 호출한다.

role_id는 새로 만들지 않고 기존 RAG-003 role 레지스트리에 이미 있는 값을 재사용한다
(ai/rag/orchestration/role_mapping.py의 competition/government_support 매핑에서 이미 확인된 값:
planning_expert -> "planning"(문서 구조·기획 관점), dev_expert -> "technology"(기술 구성·구현
가능성)가 기존 위원들에도 쓰이고 있다). ai/meeting을 import하지 않는다(회의 ↔ RAG 분리 유지,
기존 meeting_evidence_service.py와 같은 원칙).
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from ai.rag.integration.meeting_evidence_adapter import build_meeting_retrieved_evidence
from ai.rag.integration.schemas import PersonaRoleSearchResponse
from ai.rag.role_retrieval.service import RoleAwareRetrievalService

logger = logging.getLogger(__name__)

EvidenceLookup = Callable[[str, str], list[dict]]

# persona_id -> RAG-003 role_id. ideation은 committee 화이트리스트가 없는 자유 모드라
# role_mapping.py의 strict 정책(매핑 없으면 예외)을 그대로 따르지 않고, 매핑에 없는
# persona_id는 조용히 None(semantic-only 검색)으로 처리한다 — 진행자(ideation_facilitator)처럼
# 애초에 근거 검색이 필요 없는 역할도 있기 때문이다.
_PERSONA_ROLE_MAPPING: dict[str, str] = {
    "planning_expert": "planning",
    "dev_expert": "technology",
}


def resolve_ideation_role_id(persona_id: str) -> Optional[str]:
    """ideation 전문가 persona_id에 대응하는 RAG-003 role_id. 매핑에 없으면 None."""
    return _PERSONA_ROLE_MAPPING.get(persona_id)


def search_ideation_evidence(
    persona_id: str,
    topic_query: str,
    project_id: str,
    role_retrieval_service: RoleAwareRetrievalService,
    top_k: int = 5,
) -> list[dict]:
    """전문가 1명의 이번 턴 근거를 검색해 회의 그래프가 바로 쓸 수 있는 plain dict 목록으로
    반환한다. 검색 결과가 없거나 검색 자체가 실패하면 빈 리스트를 반환한다(fail-closed) —
    근거 없음은 ideation_common.txt의 근거 사용 규칙("근거 부족"으로 표시하고 사용자에게
    필요한 정보를 요청)이 프롬프트 레벨에서 처리하도록 위임한다."""
    role_id = resolve_ideation_role_id(persona_id)
    try:
        role_response = role_retrieval_service.search_by_role(
            query=topic_query,
            project_id=project_id,
            role_id=role_id,
            top_k=top_k,
        )
    except Exception:
        logger.exception(
            "[IDEATION_EVIDENCE_SEARCH_FAILED] persona_id=%s role_id=%s project_id=%s",
            persona_id,
            role_id,
            project_id,
        )
        return []

    items = build_meeting_retrieved_evidence(
        [PersonaRoleSearchResponse(persona_id=persona_id, response=role_response, role_id=role_id)]
    )
    return [dict(item) for item in items]


def make_ideation_evidence_lookup(
    project_id: str,
    role_retrieval_service: RoleAwareRetrievalService,
    top_k: int = 5,
) -> EvidenceLookup:
    """ai/meeting/graph/ideation_nodes.py::make_ideation_expert_node(evidence_lookup=...)에
    그대로 넘길 수 있는 Callable(persona_id, topic_query) -> list[dict]를 만든다."""

    def lookup(persona_id: str, topic_query: str) -> list[dict]:
        return search_ideation_evidence(
            persona_id, topic_query, project_id, role_retrieval_service, top_k=top_k
        )

    return lookup


__all__ = [
    "EvidenceLookup",
    "resolve_ideation_role_id",
    "search_ideation_evidence",
    "make_ideation_evidence_lookup",
]
