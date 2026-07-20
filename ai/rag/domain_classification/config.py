"""
Domain Classification Config
================================
ai.rag.evidence_sufficiency.config의 임계값 설정 패턴(BaseModel + Field(ge=/le=))을
그대로 따른다.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

DEFAULT_MIN_CONFIDENCE = 0.6
DEFAULT_MAX_INPUT_CHARS = 6000


class DomainClassificationConfig(BaseModel):
    """분류 서비스 동작을 조정하는 설정.

    min_confidence: 이 값 미만이면 LLM이 어떤 라벨을 골랐든 최종 결과를
        UNKNOWN으로 강등한다 — 도메인을 함부로 확정하지 않기 위한 안전장치.
    max_input_chars: chunks에서 텍스트를 구성할 때 프롬프트에 넣을 최대 글자 수.
        공고문 앞부분(제목/개요/사업 성격이 보통 가장 먼저 드러나는 구간)부터
        채우고 넘치는 뒷부분은 자른다.
    """

    min_confidence: float = Field(DEFAULT_MIN_CONFIDENCE, ge=0.0, le=1.0)
    max_input_chars: int = Field(DEFAULT_MAX_INPUT_CHARS, gt=0)


__all__ = [
    "DEFAULT_MIN_CONFIDENCE",
    "DEFAULT_MAX_INPUT_CHARS",
    "DomainClassificationConfig",
]
