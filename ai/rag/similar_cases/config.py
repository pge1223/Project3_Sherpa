"""
Similar Case Search Configuration (RAG-006)
=================================================
컬렉션 이름과 검색 임계값을 서비스 코드에 하드코딩하지 않고 여기서만 관리한다.
ai/rag의 기존 config.py들(ai.rag.converters.config 등)과 동일하게 pydantic-settings 없이
os.environ을 직접 읽는 이 프로젝트의 ai/rag 스타일을 따른다.

지원 환경변수:
    RAG_SIMILAR_CASES_COLLECTION   (기본 "similar_success_cases")
    RAG_SIMILAR_CASES_TOP_K        (기본 5)
    RAG_SIMILAR_CASES_MIN_SCORE    (기본 0.5)
"""

import os
from typing import Optional

from pydantic import BaseModel, Field, model_validator

DEFAULT_COLLECTION_NAME: str = "similar_success_cases"
DEFAULT_TOP_K: int = 5
DEFAULT_MIN_SCORE: float = 0.5
DEFAULT_MAX_TOP_K: int = 50

# 사례 청크를 chunk 단위로 넉넉히 가져온 뒤 case_id 기준으로 집계해서 최종 top_k개
# 사례를 뽑는다 (한 사례에 여러 청크가 걸릴 수 있으므로). candidate_k = top_k * 이 배수.
DEFAULT_CANDIDATE_K_MULTIPLIER: int = 4

# 사례 1건당 근거로 첨부할 최대 청크 수
DEFAULT_MAX_EVIDENCE_PER_CASE: int = 3


def _env_str(name: str) -> Optional[str]:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return None
    return value


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default


class SimilarCaseConfig(BaseModel):
    """사례 색인/검색 실행 설정."""

    collection_name: str = Field(
        default_factory=lambda: _env_str("RAG_SIMILAR_CASES_COLLECTION") or DEFAULT_COLLECTION_NAME
    )
    top_k: int = Field(default_factory=lambda: _env_int("RAG_SIMILAR_CASES_TOP_K", DEFAULT_TOP_K), ge=1)
    min_score: float = Field(
        default_factory=lambda: _env_float("RAG_SIMILAR_CASES_MIN_SCORE", DEFAULT_MIN_SCORE)
    )
    max_top_k: int = Field(default=DEFAULT_MAX_TOP_K, ge=1)
    candidate_k_multiplier: int = Field(default=DEFAULT_CANDIDATE_K_MULTIPLIER, ge=1)
    max_evidence_per_case: int = Field(default=DEFAULT_MAX_EVIDENCE_PER_CASE, ge=1)

    # 도메인 metadata 필터로 검색했는데 결과가 0건이면 도메인 필터 없이 전체 사례에서
    # 다시 검색할지 여부. False면 도메인 불일치는 그대로 빈 결과를 반환한다.
    domain_filter_fallback_to_all: bool = True

    # 유사 사례는 항상 참고 자료일 뿐 현재 문서의 직접 평가 근거가 아니다 — RAG-005의
    # 근거 충족도 판정이나 숫자 점수 허용 정책에 영향을 주지 않는다는 것을 명시하는
    # 상수 플래그. False로 바꿀 수 있는 설정이 아니라 항상 True (문서화 목적).
    reference_only: bool = Field(default=True, frozen=True)

    @model_validator(mode="after")
    def _top_k_within_max(self) -> "SimilarCaseConfig":
        if self.top_k > self.max_top_k:
            raise ValueError(f"top_k({self.top_k})는 max_top_k({self.max_top_k})를 초과할 수 없습니다")
        return self


__all__ = [
    "SimilarCaseConfig",
    "DEFAULT_COLLECTION_NAME",
    "DEFAULT_TOP_K",
    "DEFAULT_MIN_SCORE",
    "DEFAULT_MAX_TOP_K",
    "DEFAULT_CANDIDATE_K_MULTIPLIER",
    "DEFAULT_MAX_EVIDENCE_PER_CASE",
]
