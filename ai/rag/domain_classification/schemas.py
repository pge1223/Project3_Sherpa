"""
Domain Classification Schemas (DOM-001)
===========================================
공고문/평가 대상 문서의 청킹 결과 또는 정제된 텍스트를 받아 competition /
government_support / startup 중 하나로 분류하고, 확신이 낮으면 unknown으로
남긴다. 이 결과를 project.domain(또는 doc_type)에 실제로 반영할지는 backend의
몫이며, 사용자가 DOM-002(수동 도메인 변경, backend/app/api/routes/projects.py의
PATCH /{project_id}/domain)로 언제든 덮어쓸 수 있다는 전제를 유지한다 — 이
모듈은 그 값을 직접 쓰지 않고 "제안"만 반환한다.

startup은 ai/meeting/personas/startup.json(committee 구성)까지는 있지만
rubric_mapping_startup.json이 아직 없어 회의를 실제로 진행할 순 없다. 이
모듈은 그 사실과 무관하게 startup을 정상 분류 라벨로 다룬다 — "분류 가능"과
"회의 실행 가능"은 별개다.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from ai.rag.chunking.schemas import Chunk


class DomainLabel(str, Enum):
    """분류 결과 라벨. UNKNOWN은 LLM이 확신하지 못했거나(낮은 confidence),
    응답이 알 수 없는 라벨을 줬거나, 입력 문서가 비어 있을 때 쓰는 안전한 기본값이다."""

    COMPETITION = "competition"
    GOVERNMENT_SUPPORT = "government_support"
    STARTUP = "startup"
    UNKNOWN = "unknown"


# LLM이 실제로 판단해야 하는 라벨 집합(UNKNOWN은 LLM에게 직접 고르게 하지 않고,
# 이 셋 중 확신이 없을 때 서비스가 강등시키는 값이라 제외한다).
KNOWN_DOMAIN_LABELS: tuple[DomainLabel, ...] = (
    DomainLabel.COMPETITION,
    DomainLabel.GOVERNMENT_SUPPORT,
    DomainLabel.STARTUP,
)


class DomainClassificationResult(BaseModel):
    """DomainClassificationService.classify()의 반환값."""

    domain: DomainLabel = Field(..., description="최종 분류 결과. 임계값 미달이면 UNKNOWN")
    confidence: float = Field(..., ge=0.0, le=1.0, description="LLM이 보고한(정규화된) 확신도")
    reasoning: str = Field(..., description="분류 근거(LLM이 준 설명 또는 서비스가 강등 사유를 덧붙인 설명)")
    raw_domain_label: Optional[str] = Field(
        None, description="UNKNOWN으로 강등되기 전 LLM이 실제로 응답한 원본 라벨 문자열(진단용)"
    )
    candidate_scores: dict[str, float] = Field(
        default_factory=dict, description="LLM이 라벨별 점수를 함께 준 경우에만 채워지는 선택 정보"
    )
    warnings: list[str] = Field(default_factory=list)


class DomainClassificationRequest(BaseModel):
    """classify()의 입력. 특정 파일 형식(PDF/HWPX/URL)에 결합하지 않기 위해
    청킹 결과(Chunk 목록) 또는 이미 정제된 텍스트 중 하나(또는 둘 다)를 받는다.
    text가 있으면 그대로 쓰고, 없으면 chunks에서 텍스트를 구성한다."""

    chunks: list[Chunk] = Field(default_factory=list)
    text: Optional[str] = Field(
        None, description="정제된 텍스트를 직접 넘길 때 사용. 주어지면 chunks보다 우선한다"
    )
