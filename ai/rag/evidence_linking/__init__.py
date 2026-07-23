"""
Evidence Linking Module (RAG-004)
=====================================
LangGraph 위원 노드가 생성한 평가 의견을, 그 근거가 된 원문 청크(문서명/페이지/섹션/
인용문)와 연결한다. LLM 호출 없음 — 이미 검색된 결과에서만 규칙 기반으로 근거를 고른다.

사용 예시:
    from ai.rag.role_retrieval import RoleAwareRetrievalService
    from ai.rag.evidence_linking import EvidenceLinkingService

    role_response = role_retrieval_service.search_by_role(
        query=question, project_id=project_id, role_id="finance", top_k=5,
    )

    evidence_service = EvidenceLinkingService()
    linked = evidence_service.link_evidence(
        opinion="예산 산정 근거가 부족합니다.",
        search_results=role_response.results,
        role_id=role_response.role_id,
        role_name=role_response.role_name,
    )
    linked.has_evidence  # bool
    linked.evidence      # list[EvidenceSource]
"""

from ai.rag.evidence_linking.claim_grounding import (
    Claim,
    ClaimGroundingResult,
    UnsupportedClaim,
    ground_claims,
    has_hard_grounding_failure,
)
from ai.rag.evidence_linking.config import EvidenceLinkingConfig
from ai.rag.evidence_linking.linker import build_linked_evaluation, resolve_score
from ai.rag.evidence_linking.quote_extractor import extract_quote, select_best_sentence, split_sentences
from ai.rag.evidence_linking.schemas import EvidenceSource, LinkedEvaluation
from ai.rag.evidence_linking.service import EvidenceLinkingService

__all__ = [
    "EvidenceLinkingService",
    "EvidenceLinkingConfig",
    "EvidenceSource",
    "LinkedEvaluation",
    "build_linked_evaluation",
    "resolve_score",
    "extract_quote",
    "select_best_sentence",
    "split_sentences",
    "Claim",
    "ClaimGroundingResult",
    "UnsupportedClaim",
    "ground_claims",
    "has_hard_grounding_failure",
]
