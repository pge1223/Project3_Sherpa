"""
Meeting Evidence Orchestration -> ai/meeting/graph 출력 계약
=================================================================
MeetingEvidenceOrchestrationService가 만들어 backend에 반환하는 plain dict 형태의
타입 힌트. run_meeting(evidence_context=...)과 reviewer 노드의 evidence_callback
반환값(ai/meeting/graph/nodes/reviewer.py의 EvidenceCallback 시그니처, ai/meeting/tests/
test_evidence_integration.py로 이미 검증됨)과 키/의미가 정확히 일치해야 한다.

여기서 정의하는 TypedDict는 런타임 검증을 하지 않는다 — 실제 값은 항상 plain dict/list로
반환되며(ai.rag.integration.meeting_evidence_adapter와 동일 관례), TypedDict는 정적 타입
힌트로만 쓰인다.
"""

from __future__ import annotations

from typing import TypedDict


class PreSufficiencyDict(TypedDict):
    """evidence_context[].sufficiency — RAG-005 사전 판정(assess_role_response 결과)."""

    status: str
    prompt_guard: str
    allow_numeric_score: bool
    allow_definitive_judgment: bool


class MeetingEvidenceContextEntry(TypedDict):
    """run_meeting(evidence_context=...)에 그대로 넘기는 (persona_id, criterion_id) 1건."""

    persona_id: str
    criterion_id: str
    retrieved_evidence: list[dict]
    sufficiency: PreSufficiencyDict


class FinalSufficiencyDict(TypedDict):
    """evidence_callback 반환값의 sufficiency — RAG-005 최종 판정(assess_linked_evaluation 결과)."""

    status: str
    allow_numeric_score: bool
    allow_definitive_judgment: bool
    reason_codes: list[str]


class EvidenceCallbackResult(TypedDict):
    """evidence_callback(persona_id, criterion_id, review_item)의 반환값.

    linked_evidence_refs는 항상 RAG-004 to_linked_evidence_refs() 결과만 담는다(A안) —
    위원이 review_item에서 자체 생성한 evidence_refs는 여기 포함하지 않는다."""

    linked_evidence_refs: list[dict]
    sufficiency: FinalSufficiencyDict


__all__ = [
    "PreSufficiencyDict",
    "MeetingEvidenceContextEntry",
    "FinalSufficiencyDict",
    "EvidenceCallbackResult",
]
