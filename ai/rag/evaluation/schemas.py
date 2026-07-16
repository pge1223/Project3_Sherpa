"""
Evaluation Schemas
=====================
평가셋(입력)과 실행 결과 리포트(출력) Pydantic 스키마.

평가셋 스키마는 사람이 chunk_id 단위로 정답을 표시한 JSON을 검증한다 —
role_id는 domain/persona_id(/criterion_id)에 대해 ai.rag.orchestration.role_mapping
(RAG-003이 실제로 사용하는 매핑)을 그대로 재사용해 검증하므로, 지원하지 않는
domain/persona_id/role_id 조합은 여기서 조용히 통과하지 않고 ValidationError로 막힌다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from ai.rag.orchestration.role_mapping import resolve_role_id


class EvaluationCase(BaseModel):
    """평가셋의 검색 케이스 1건. relevant_chunk_ids는 사람이 직접 확인해 입력한 정답이어야 한다."""

    case_id: str
    project_id: str
    domain: str
    persona_id: str
    role_id: str
    criterion_id: Optional[str] = None
    query: str
    relevant_chunk_ids: list[str]
    expected_sufficiency: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("case_id", "project_id", "domain", "persona_id", "role_id", "query")
    @classmethod
    def _not_blank(cls, v: str, info) -> str:
        if not v or not v.strip():
            raise ValueError(f"{info.field_name}은(는) 빈 문자열일 수 없습니다")
        return v

    @field_validator("relevant_chunk_ids")
    @classmethod
    def _validate_relevant_chunk_ids(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("relevant_chunk_ids는 최소 1개 이상이어야 합니다")
        deduped = list(dict.fromkeys(v))
        if len(deduped) != len(v):
            raise ValueError("relevant_chunk_ids에 중복된 chunk_id가 있습니다")
        return deduped

    @model_validator(mode="after")
    def _role_id_matches_mapping(self) -> "EvaluationCase":
        # 지원하지 않는 domain/persona_id/criterion_id 조합이면 resolve_role_id가
        # PersonaRoleMappingError(ValueError 하위 클래스)를 던진다 — 그대로 ValidationError가 된다.
        expected_role_id = resolve_role_id(
            domain=self.domain,
            persona_id=self.persona_id,
            criterion_id=self.criterion_id,
        )
        if expected_role_id != self.role_id:
            raise ValueError(
                f"role_id({self.role_id!r})가 role_mapping 결과({expected_role_id!r})와 다릅니다 "
                f"(domain={self.domain!r}, persona_id={self.persona_id!r}, criterion_id={self.criterion_id!r})"
            )
        return self


class EvaluationDataset(BaseModel):
    """평가셋 전체(파일 1개 = 데이터셋 1개)."""

    dataset_name: str
    version: str
    cases: list[EvaluationCase]

    @field_validator("dataset_name", "version")
    @classmethod
    def _not_blank(cls, v: str, info) -> str:
        if not v or not v.strip():
            raise ValueError(f"{info.field_name}은(는) 빈 문자열일 수 없습니다")
        return v

    @model_validator(mode="after")
    def _validate_cases(self) -> "EvaluationDataset":
        if not self.cases:
            raise ValueError("cases는 최소 1개 이상이어야 합니다")
        seen: set[str] = set()
        for case in self.cases:
            if case.case_id in seen:
                raise ValueError(f"중복된 case_id입니다: {case.case_id!r}")
            seen.add(case.case_id)
        return self


class RetrievalSettingsSnapshot(BaseModel):
    """리포트에 기록되는 실행 당시 설정값. 여러 파일에 하드코딩하지 않고
    ai.rag.chunking.config / ai.rag.role_retrieval.config 등 실제 설정 소스에서 읽는다."""

    chunk_size: int
    chunk_overlap: int
    semantic_weight: float
    role_weight: float
    candidate_k_multiplier: int
    k_values: list[int]
    embedding_model: Optional[str] = None
    embedding_version: Optional[str] = None
    collection_name: Optional[str] = None


class CaseMetrics(BaseModel):
    """평가 케이스 1건의 검색 결과 및 지표."""

    case_id: str
    project_id: str
    domain: str
    persona_id: str
    role_id: str
    criterion_id: Optional[str] = None
    query: str
    retrieved_chunk_ids: list[str] = Field(default_factory=list, description="중복 제거된, 점수순 chunk_id")
    relevant_chunk_ids: list[str] = Field(default_factory=list, description="정답 chunk_id (순서 무관)")
    reciprocal_rank: float
    precision_at_k: dict[int, float] = Field(default_factory=dict)
    recall_at_k: dict[int, float] = Field(default_factory=dict)
    hit_rate_at_k: dict[int, float] = Field(default_factory=dict)
    ndcg_at_k: dict[int, float] = Field(default_factory=dict)
    result_count: int = 0
    warnings: list[str] = Field(default_factory=list)


class AggregateMetrics(BaseModel):
    """전체 케이스 평균 지표."""

    mean_precision_at_k: dict[int, float] = Field(default_factory=dict)
    mean_recall_at_k: dict[int, float] = Field(default_factory=dict)
    mean_hit_rate_at_k: dict[int, float] = Field(default_factory=dict)
    mean_ndcg_at_k: dict[int, float] = Field(default_factory=dict)
    mrr: float
    case_count: int
    empty_result_case_count: int


class EvaluationReport(BaseModel):
    """평가 실행 1회의 최종 결과. JSON 직렬화 가능(model_dump_json)."""

    dataset_name: str
    dataset_version: str
    run_id: str
    executed_at: datetime
    settings: RetrievalSettingsSnapshot
    case_metrics: list[CaseMetrics]
    aggregate: AggregateMetrics
    notes: Optional[str] = None
