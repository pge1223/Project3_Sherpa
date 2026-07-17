"""
Meeting Evidence Orchestration Service
===========================================
RAG-003(RoleAwareRetrievalService)/RAG-004(EvidenceLinkingService)/RAG-005
(EvidenceSufficiencyService)를 조립해, backend(윤한)가 run_meeting()에 넘길
evidence_context와 evidence_callback을 만드는 상위 계층.

ai/meeting/graph는 이미 이 계약(evidence_context/evidence_callback)을 완성해 테스트까지
끝낸 상태다(ai/meeting/graph/run.py, ai/meeting/tests/test_evidence_integration.py) —
이 모듈은 ai.meeting을 import하지 않고, run_meeting()이 그대로 받을 수 있는 plain
dict/list만 반환한다(회의 ↔ RAG 분리 유지).

persona_id -> RAG-003 role_id 매핑은 role_mapping.resolve_role_id()에 위임한다(기본값
strict — 매핑이 없으면 PersonaRoleMappingError). RAG 처리 중 오류가 나면 fail-open(점수
허용)하지 않고 보수적으로 insufficient/미채점 결과를 반환한다.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from ai.rag.evidence_linking.service import EvidenceLinkingService
from ai.rag.evidence_sufficiency.config import EvidenceSufficiencyConfig
from ai.rag.evidence_sufficiency.prompt_guard import build_prompt_guard
from ai.rag.evidence_sufficiency.schemas import EvidenceSufficiencyStatus
from ai.rag.evidence_sufficiency.service import EvidenceSufficiencyService
from ai.rag.integration.meeting_evidence_adapter import (
    build_meeting_retrieved_evidence,
    to_linked_evidence_refs,
)
from ai.rag.integration.schemas import PersonaRoleSearchResponse
from ai.rag.orchestration.role_mapping import (
    PersonaRoleMappingError,
    RoleMappingConfig,
    resolve_role_id,
)
from ai.rag.role_retrieval.schemas import RoleSearchResponse
from ai.rag.role_retrieval.service import RoleAwareRetrievalService

logger = logging.getLogger(__name__)

EvidenceCallback = Callable[[str, str, dict], dict]

# criterion마다 review_item에서 근거 관련성 판단(RAG-004 is_relevant_candidate)에 쓸
# 텍스트를 뽑는 필드. review_item은 reviewer_prompt.txt 출력(raw) 1개 항목이라
# "criterion 전체 의견을 나타내는 단일 필드"가 없어, 위원이 실제로 채운 항목들을 모아
# opinion 텍스트를 구성한다.
_OPINION_FIELDS = ("criterion_name", "strengths", "weaknesses", "improvement_actions")


def _fail_closed_callback_result(reason_codes: Optional[list[str]] = None) -> dict[str, Any]:
    """RAG-004/005 처리 실패 또는 근거 없음 시 반환하는 보수적 결과(fail-open 금지)."""
    return {
        "linked_evidence_refs": [],
        "sufficiency": {
            "status": EvidenceSufficiencyStatus.INSUFFICIENT.value,
            "allow_numeric_score": False,
            "allow_definitive_judgment": False,
            "reason_codes": reason_codes or [],
        },
    }


def _fail_closed_pre_sufficiency() -> dict[str, Any]:
    """RAG-003/005 사전 검색·판정 실패 시 evidence_context 항목에 채우는 보수적 값."""
    return {
        "status": EvidenceSufficiencyStatus.INSUFFICIENT.value,
        "prompt_guard": build_prompt_guard(EvidenceSufficiencyStatus.INSUFFICIENT),
        "allow_numeric_score": False,
        "allow_definitive_judgment": False,
    }


def _build_opinion_text(review_item: dict[str, Any]) -> str:
    """review_item(reviewer raw 출력의 review_items[i])에서 RAG-004 관련성 판단용 텍스트를 만든다."""
    parts: list[str] = []
    for field in _OPINION_FIELDS:
        value = review_item.get(field)
        if not value:
            continue
        if isinstance(value, list):
            parts.extend(str(v) for v in value if v)
        else:
            parts.append(str(value))
    return " ".join(parts)


def iter_persona_criteria(rubric_mapping: dict[str, Any]) -> list[tuple[str, str, str]]:
    """rubric_mapping["rubric"][].primary_persona_id/secondary_persona_id에서
    (persona_id, criterion_id, criterion_name) 조합을 뽑는다. 같은 (persona_id, criterion_id)
    조합은 한 번만 남긴다(주 담당/보조 위원이 우연히 같은 값이어도 중복 검색하지 않음)."""
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str, str]] = []
    for item in rubric_mapping["rubric"]:
        criterion_id = item["criterion_id"]
        criterion_name = item["criterion_name"]
        for persona_key in ("primary_persona_id", "secondary_persona_id"):
            persona_id = item.get(persona_key)
            if not persona_id:
                continue
            key = (persona_id, criterion_id)
            if key in seen:
                continue
            seen.add(key)
            out.append((persona_id, criterion_id, criterion_name))
    return out


class MeetingEvidenceOrchestrationService:
    """analyze_project()가 회의 실행 전/후에 호출하는 RAG-003/004/005 조립 계층.

    한 인스턴스는 회의 1회(prepare_meeting_evidence 1회 호출) 동안만 재사용한다 —
    prepare_meeting_evidence()가 채운 검색 결과 캐시를 create_evidence_callback()이
    반환하는 콜백이 그대로 참조하기 때문에, 다른 회의의 캐시와 섞이면 안 된다.
    """

    def __init__(
        self,
        *,
        role_retrieval_service: RoleAwareRetrievalService,
        evidence_linking_service: EvidenceLinkingService,
        evidence_sufficiency_service: EvidenceSufficiencyService,
        role_mapping_config: Optional[RoleMappingConfig] = None,
        sufficiency_config: Optional[EvidenceSufficiencyConfig] = None,
        top_k: int = 5,
    ):
        self._role_retrieval_service = role_retrieval_service
        self._evidence_linking_service = evidence_linking_service
        self._evidence_sufficiency_service = evidence_sufficiency_service
        self._role_mapping_config = role_mapping_config or RoleMappingConfig()
        self._sufficiency_config = sufficiency_config
        self._top_k = top_k
        # (persona_id, criterion_id) -> RAG-003 검색 결과. create_evidence_callback()이
        # 참조하는 이 회의 전용 캐시 — RAG-004가 "새 검색을 하지 않고 이미 받은 결과만
        # 연결한다"는 계약(evidence_linking/service.py 상단 docstring)을 지키기 위함이다.
        self._search_cache: dict[tuple[str, str], RoleSearchResponse] = {}

    def prepare_meeting_evidence(
        self,
        *,
        project_id: str,
        domain: str,
        rubric_mapping: dict[str, Any],
        trace_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """committee가 담당하는 (persona_id, criterion_id)마다 RAG-003 검색 ->
        RAG-005 사전 판정 -> build_meeting_retrieved_evidence()를 거쳐 run_meeting()에
        넘길 evidence_context를 만든다. 반환값은 JSON 직렬화 가능한 plain list[dict]다."""
        self._search_cache = {}
        entries: list[dict[str, Any]] = []

        for persona_id, criterion_id, criterion_name in iter_persona_criteria(rubric_mapping):
            entries.append(
                self._prepare_one(
                    project_id=project_id,
                    domain=domain,
                    persona_id=persona_id,
                    criterion_id=criterion_id,
                    criterion_name=criterion_name,
                    trace_id=trace_id,
                )
            )
        return entries

    def _prepare_one(
        self,
        *,
        project_id: str,
        domain: str,
        persona_id: str,
        criterion_id: str,
        criterion_name: str,
        trace_id: Optional[str],
    ) -> dict[str, Any]:
        # role mapping 누락(PersonaRoleMappingError)은 그대로 올려 backend가 즉시 알게 한다 —
        # "매핑 없으면 semantic-only로 조용히 넘어가지 않는다"는 정책을 여기서 흡수해
        # fail-closed 처리해버리면 설정 오류를 회의 결과 품질 저하로만 관찰하게 되어 정책 취지에 어긋난다.
        role_id = resolve_role_id(
            domain=domain,
            persona_id=persona_id,
            criterion_id=criterion_id,
            config=self._role_mapping_config,
        )

        try:
            role_response = self._role_retrieval_service.search_by_role(
                query=criterion_name,
                project_id=project_id,
                role_id=role_id,
                top_k=self._top_k,
            )
        except Exception:
            # 그 외(RAG-003 검색 실패 등)는 fail-closed로 이 (persona, criterion)만 미채점 처리한다.
            logger.exception(
                "[MEETING_EVIDENCE_PREPARE_FAILED] trace_id=%s persona_id=%s criterion_id=%s",
                trace_id,
                persona_id,
                criterion_id,
            )
            return {
                "persona_id": persona_id,
                "criterion_id": criterion_id,
                "retrieved_evidence": [],
                "sufficiency": _fail_closed_pre_sufficiency(),
            }

        self._search_cache[(persona_id, criterion_id)] = role_response

        try:
            pre_sufficiency = self._evidence_sufficiency_service.assess_role_response(
                role_response, trace_id=trace_id, config=self._sufficiency_config
            )
        except Exception:
            logger.exception(
                "[MEETING_EVIDENCE_PREPARE_SUFFICIENCY_FAILED] trace_id=%s persona_id=%s criterion_id=%s",
                trace_id,
                persona_id,
                criterion_id,
            )
            return {
                "persona_id": persona_id,
                "criterion_id": criterion_id,
                "retrieved_evidence": [],
                "sufficiency": _fail_closed_pre_sufficiency(),
            }

        retrieved_evidence = build_meeting_retrieved_evidence(
            [PersonaRoleSearchResponse(persona_id=persona_id, response=role_response, role_id=role_id)]
        )

        return {
            "persona_id": persona_id,
            "criterion_id": criterion_id,
            "retrieved_evidence": [dict(item) for item in retrieved_evidence],
            "sufficiency": {
                "status": pre_sufficiency.status.value,
                "prompt_guard": pre_sufficiency.prompt_guard,
                "allow_numeric_score": pre_sufficiency.allow_numeric_score,
                "allow_definitive_judgment": pre_sufficiency.allow_definitive_judgment,
            },
        }

    def create_evidence_callback(self, *, trace_id: Optional[str] = None) -> EvidenceCallback:
        """run_meeting(evidence_callback=...)에 그대로 넘길 콜백을 만든다.

        직전 prepare_meeting_evidence() 호출이 채운 검색 결과 캐시를 참조하므로,
        반드시 같은 인스턴스에서 prepare_meeting_evidence()를 먼저 호출한 뒤에 써야 한다."""

        def callback(persona_id: str, criterion_id: str, review_item: dict[str, Any]) -> dict[str, Any]:
            role_response = self._search_cache.get((persona_id, criterion_id))
            if role_response is None or not role_response.results:
                return _fail_closed_callback_result(reason_codes=["NO_LINKED_EVIDENCE"])

            try:
                opinion = _build_opinion_text(review_item)
                linked_evaluation = self._evidence_linking_service.link_evidence(
                    opinion=opinion,
                    search_results=role_response.results,
                    role_id=role_response.role_id,
                    role_name=role_response.role_name,
                )
                final_sufficiency = self._evidence_sufficiency_service.assess_linked_evaluation(
                    linked_evaluation, trace_id=trace_id, config=self._sufficiency_config
                )
            except Exception:
                logger.exception(
                    "[MEETING_EVIDENCE_CALLBACK_FAILED] trace_id=%s persona_id=%s criterion_id=%s",
                    trace_id,
                    persona_id,
                    criterion_id,
                )
                return _fail_closed_callback_result()

            linked_refs = [dict(ref) for ref in to_linked_evidence_refs(linked_evaluation)]
            return {
                "linked_evidence_refs": linked_refs,
                "sufficiency": {
                    "status": final_sufficiency.status.value,
                    "allow_numeric_score": final_sufficiency.allow_numeric_score,
                    "allow_definitive_judgment": final_sufficiency.allow_definitive_judgment,
                    "reason_codes": [code.value for code in final_sufficiency.reason_codes],
                },
            }

        return callback


__all__ = [
    "MeetingEvidenceOrchestrationService",
    "EvidenceCallback",
    "iter_persona_criteria",
    "PersonaRoleMappingError",
]
