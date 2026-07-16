"""
RAG -> 회의 파이프라인 출력 계약
====================================
RAG-003(RoleAwareRetrievalService)/RAG-004(EvidenceLinkingService)의 결과를
ai/meeting/graph가 소비하는 plain dict 형태로 옮기기 위한 타입 계약.

여기서 정의하는 TypedDict는 런타임 검증을 하지 않는다 — 실제 값은 항상
plain dict로 반환되며(EvidencePool 등 회의 쪽 코드가 `.get()`으로 읽는 관례를
따름), TypedDict는 정적 타입 힌트로만 쓰인다.
"""

from dataclasses import dataclass
from typing import Optional, TypedDict

from ai.rag.role_retrieval.schemas import RoleSearchResponse


class MeetingRetrievedEvidence(TypedDict):
    """run_meeting(retrieved_evidence=...)에 그대로 넘길 수 있는 근거 1건.

    chunk_id/document_name/page/section/text/score는 기존 EvidencePool이 읽는
    필드라 이름과 의미를 그대로 유지한다(ai/meeting/graph/evidence.py 참고)."""

    chunk_id: str
    document_id: str
    persona_id: str
    role_id: Optional[str]

    document_name: Optional[str]
    section: Optional[str]
    page: Optional[int]

    location_number: Optional[int]
    location_type: Optional[str]

    text: str

    semantic_score: Optional[float]
    role_score: Optional[float]
    final_score: Optional[float]
    score: float


class MeetingLinkedEvidenceRef(TypedDict):
    """RAG-004 LinkedEvaluation.evidence[] 1건을 (document_id, chunk_id) 키가
    보존된 plain dict로 옮긴 것. evidence_id는 만들지 않는다 — 회의 쪽이
    (document_id, chunk_id)로 자신이 이미 발급한 evidence_id를 역조회한다."""

    document_id: str
    chunk_id: str
    quote: str

    document_name: Optional[str]
    section: Optional[str]
    page: Optional[int]

    semantic_score: Optional[float]
    role_score: Optional[float]
    final_score: Optional[float]


@dataclass(frozen=True)
class PersonaRoleSearchResponse:
    """persona_id/role_id 정보가 없는 RoleSearchResponse 하나를 build_meeting_retrieved_evidence()에
    넘기기 위한 입력 래퍼. RoleSearchResponse.role_id는 검색에 실제 사용된 role_id를 담지만,
    role_id=None(semantic-only fallback)으로 검색한 persona도 있을 수 있어 persona_id는 항상
    호출자가 명시적으로 넘긴다."""

    persona_id: str
    response: RoleSearchResponse
    role_id: Optional[str] = None
