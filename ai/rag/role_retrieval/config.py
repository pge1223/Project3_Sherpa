"""
Role-Aware Retrieval Configuration Defaults
==============================================
RAG-002 검색 결과를 심사위원 role 관점으로 재정렬할 때 쓰는 가중치/제한값.
튜닝이 필요하면 이 파일의 상수 또는 RoleRerankConfig 인스턴스만 바꾸면 된다.
"""

from pydantic import BaseModel, field_validator

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

# 중복/과도 중첩 청크 억제 (단일 search_by_role() 호출 내부에서만 적용 — 서로 다른 persona가
# 같은 근거를 쓰는 것은 정상이므로 호출 간에는 전혀 공유하지 않는다).
# 공백/줄바꿈만 다른 경우는 정규화 후 완전 일치(계수 1.0)로 걸리고, chunk_overlap으로 인해
# 한쪽이 다른 쪽 내용을 대부분 포함하는 인접 청크는 overlap coefficient(교집합 단어 수 / 더
# 작은 쪽 단어 집합 크기 — 두 집합 크기가 다를 때 "포함 관계"를 Jaccard보다 잘 잡아낸다)로
# 걸러낸다.
DEFAULT_DUPLICATE_CONTENT_OVERLAP_COEFFICIENT: float = 0.8

# 최종 점수 차이가 이 값 이내면 "동률에 가깝다"고 보고, 이미 뽑힌 결과와 다른 section을 가진
# 후보를 우선한다(다양성). 점수 차이가 이보다 크면 점수 순서를 그대로 따른다.
DEFAULT_DIVERSITY_SCORE_EPSILON: float = 0.05


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

    duplicate_content_overlap_coefficient: float = DEFAULT_DUPLICATE_CONTENT_OVERLAP_COEFFICIENT
    diversity_score_epsilon: float = DEFAULT_DIVERSITY_SCORE_EPSILON

    @field_validator("duplicate_content_overlap_coefficient")
    @classmethod
    def _overlap_coefficient_must_be_in_unit_range(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError("duplicate_content_overlap_coefficient는 0 이상 1 이하여야 합니다")
        return v

    @field_validator("diversity_score_epsilon")
    @classmethod
    def _diversity_score_epsilon_must_be_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("diversity_score_epsilon은 0 이상이어야 합니다")
        return v


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
    "DEFAULT_DUPLICATE_CONTENT_OVERLAP_COEFFICIENT",
    "DEFAULT_DIVERSITY_SCORE_EPSILON",
]
