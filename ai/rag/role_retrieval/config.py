"""
Role-Aware Retrieval Configuration Defaults
==============================================
RAG-002 검색 결과를 심사위원 role 관점으로 재정렬할 때 쓰는 가중치/제한값.
튜닝이 필요하면 이 파일의 상수 또는 RoleRerankConfig 인스턴스만 바꾸면 된다.
"""

from pydantic import BaseModel

# semantic_score와 role_score를 최종 점수로 결합할 때의 가중치
DEFAULT_SEMANTIC_WEIGHT: float = 0.75
DEFAULT_ROLE_WEIGHT: float = 0.25

# candidate_k 기본값 = top_k * DEFAULT_CANDIDATE_K_MULTIPLIER
DEFAULT_CANDIDATE_K_MULTIPLIER: int = 3

# 키워드 매칭 1건당 role_score에 더해지는 가중치 (필드별로 다르게 — section_title이 가장 신뢰도 높음)
DEFAULT_CONTENT_HIT_WEIGHT: float = 0.15
DEFAULT_SECTION_HIT_WEIGHT: float = 0.35
DEFAULT_TITLE_HIT_WEIGHT: float = 0.10

# 키워드 중복으로 점수가 무한정 커지지 않도록 필드별 최대 매칭 건수 제한
DEFAULT_MAX_CONTENT_HITS: int = 3
DEFAULT_MAX_SECTION_HITS: int = 2
DEFAULT_MAX_TITLE_HITS: int = 2

# role_score 자체의 상한 (semantic_score와 동일한 [0, 1] 스케일로 맞추기 위함)
DEFAULT_MAX_ROLE_SCORE: float = 1.0


class RoleRerankConfig(BaseModel):
    """역할 재정렬 가중치. 서비스 생성 시 주입해 role별/환경별로 다르게 튜닝할 수 있다."""

    semantic_weight: float = DEFAULT_SEMANTIC_WEIGHT
    role_weight: float = DEFAULT_ROLE_WEIGHT

    content_hit_weight: float = DEFAULT_CONTENT_HIT_WEIGHT
    section_hit_weight: float = DEFAULT_SECTION_HIT_WEIGHT
    title_hit_weight: float = DEFAULT_TITLE_HIT_WEIGHT

    max_content_hits: int = DEFAULT_MAX_CONTENT_HITS
    max_section_hits: int = DEFAULT_MAX_SECTION_HITS
    max_title_hits: int = DEFAULT_MAX_TITLE_HITS

    max_role_score: float = DEFAULT_MAX_ROLE_SCORE
    candidate_k_multiplier: int = DEFAULT_CANDIDATE_K_MULTIPLIER


__all__ = [
    "RoleRerankConfig",
    "DEFAULT_SEMANTIC_WEIGHT",
    "DEFAULT_ROLE_WEIGHT",
    "DEFAULT_CANDIDATE_K_MULTIPLIER",
    "DEFAULT_CONTENT_HIT_WEIGHT",
    "DEFAULT_SECTION_HIT_WEIGHT",
    "DEFAULT_TITLE_HIT_WEIGHT",
    "DEFAULT_MAX_CONTENT_HITS",
    "DEFAULT_MAX_SECTION_HITS",
    "DEFAULT_MAX_TITLE_HITS",
    "DEFAULT_MAX_ROLE_SCORE",
]
