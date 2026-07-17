"""
Meeting Evidence Orchestration (RAG-003·004·005 -> ai/meeting/graph 연동)
================================================================================
backend(윤한)가 analyze_project()에서 호출하는 상위 계층. 자세한 사용법은
README.md 참고.
"""

from ai.rag.orchestration.meeting_evidence_service import (
    EvidenceCallback,
    MeetingEvidenceOrchestrationService,
    PersonaRoleMappingError,
    iter_persona_criteria,
)
from ai.rag.orchestration.role_mapping import RoleMappingConfig, resolve_role_id, supported_domains

__all__ = [
    "MeetingEvidenceOrchestrationService",
    "EvidenceCallback",
    "iter_persona_criteria",
    "PersonaRoleMappingError",
    "RoleMappingConfig",
    "resolve_role_id",
    "supported_domains",
]
