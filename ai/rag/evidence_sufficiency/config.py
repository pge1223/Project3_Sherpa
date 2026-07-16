"""
Evidence Sufficiency Configuration (RAG-005)
=================================================
검색/근거 연결 결과가 회의 위원에게 확정적 판단을 허용할 만큼 충분한지
판정할 때 쓰는 기준값. 기준을 코드에 흩어놓지 않고 여기서만 관리한다.
"""

from typing import Optional

from pydantic import BaseModel, Field, model_validator

# 이 점수 미만인 근거는 유효 근거로 세지 않는다 (RAG-004 DEFAULT_MIN_EVIDENCE_SCORE와 동일 스케일).
DEFAULT_MIN_SCORE: float = 0.3

# 최소 이 개수 이상의 유효 근거가 없으면 insufficient로 판정한다.
DEFAULT_MIN_REQUIRED_EVIDENCE: int = 1

# 이 개수 이상의 유효 근거가 있어야 sufficient로 판정한다.
DEFAULT_PREFERRED_EVIDENCE_COUNT: int = 2

# 이보다 짧은 content는 실질적인 근거로 보지 않는다.
DEFAULT_MIN_CONTENT_LENGTH: int = 10


class EvidenceSufficiencyConfig(BaseModel):
    """근거 충족 기준 설정. 서비스 호출 시 주입해 튜닝할 수 있다."""

    min_score: float = Field(default=DEFAULT_MIN_SCORE, ge=0.0, le=1.0)

    min_required_evidence: int = Field(default=DEFAULT_MIN_REQUIRED_EVIDENCE, ge=1)
    preferred_evidence_count: int = Field(default=DEFAULT_PREFERRED_EVIDENCE_COUNT, ge=1)

    min_content_length: int = Field(default=DEFAULT_MIN_CONTENT_LENGTH, ge=1)

    require_document_id: bool = True
    require_chunk_id: bool = True
    require_non_empty_content: bool = True

    deduplicate_by_document_and_chunk: bool = True

    partial_allows_definitive_judgment: bool = False
    partial_allows_numeric_score: bool = False

    sufficient_allows_numeric_score: bool = True

    @model_validator(mode="after")
    def _preferred_must_be_at_least_required(self) -> "EvidenceSufficiencyConfig":
        if self.preferred_evidence_count < self.min_required_evidence:
            raise ValueError("preferred_evidence_count는 min_required_evidence 이상이어야 합니다")
        return self


class RoleEvidenceSufficiencyConfig(BaseModel):
    """역할별 EvidenceSufficiencyConfig override 레지스트리.

    현재는 과도한 복잡성을 피하기 위해 기본 설정 하나로도 충분히 동작하며,
    역할별 기준이 필요해지면 role_overrides에 role_id -> config를 채워 넣기만 하면 된다.
    역할별 임의 기준은 여기 하드코딩하지 않고 호출자가 명시적으로 주입한다."""

    default: EvidenceSufficiencyConfig = Field(default_factory=EvidenceSufficiencyConfig)
    role_overrides: dict[str, EvidenceSufficiencyConfig] = Field(default_factory=dict)

    def resolve(self, role_id: Optional[str]) -> EvidenceSufficiencyConfig:
        if role_id is not None and role_id in self.role_overrides:
            return self.role_overrides[role_id]
        return self.default


__all__ = [
    "EvidenceSufficiencyConfig",
    "RoleEvidenceSufficiencyConfig",
    "DEFAULT_MIN_SCORE",
    "DEFAULT_MIN_REQUIRED_EVIDENCE",
    "DEFAULT_PREFERRED_EVIDENCE_COUNT",
    "DEFAULT_MIN_CONTENT_LENGTH",
]
