"""
Pydantic Schemas for HTML Content Cleaning
===========================================
ai.rag.loaders.schemas는 수정하지 않고, WebContentBlock을 그대로 재사용한다.
"""

from enum import Enum

from pydantic import BaseModel, Field

from ai.rag.loaders.schemas import WebContentBlock


class RemovalReason(str, Enum):
    """블록/섹션이 제거된 이유"""
    NAV_MENU = "nav_menu"                                   # 상단 메뉴/카테고리
    LOGIN_SIGNUP = "login_signup"                           # 로그인/회원가입
    ADVERTISEMENT = "advertisement"                         # 광고/배너
    RECOMMENDED_CONTENT = "recommended_content"             # 추천 콘텐츠/함께 보면 좋은 공모전
    NEWSLETTER = "newsletter"                               # 뉴스레터/구독
    COMPANY_INFO_FOOTER = "company_info_footer"             # 회사소개/사업자정보/공통 footer
    DUPLICATE = "duplicate"                                 # 문서 내 동일 내용 중복
    UNCLASSIFIED_STRUCTURAL_NOISE = "unclassified_structural_noise"  # 키워드 매치 없이 구조적 신호로만 판단


class CleaningMethod(str, Enum):
    """정제에 사용된 규칙 버전 (재현성 추적용)"""
    RULE_BASED_V1 = "rule_based_v1"


class RemovedBlock(BaseModel):
    """제거된 블록과 그 근거 (감사/튜닝용으로 원본 내용을 그대로 보존)"""
    block: WebContentBlock
    reason: RemovalReason
    detail: str = Field(..., description="사람이 읽을 수 있는 구체적 제거 근거")


class CleanedWebContent(BaseModel):
    """clean_page_content()의 반환 스키마. 원본 WebPageContent는 절대 mutate하지 않는다."""
    source_url: str
    original_block_count: int
    cleaned_block_count: int
    cleaned_blocks: list[WebContentBlock] = Field(default_factory=list)
    removed_blocks: list[RemovedBlock] = Field(default_factory=list)
    original_text_length: int
    cleaned_text_length: int
    retention_ratio: float = Field(..., description="cleaned_text_length / original_text_length (0~1)")
    fallback_used: bool = Field(False, description="정제 결과가 비거나 지나치게 적어 원본 전체 유지로 전환했는지 여부")
    warnings: list[str] = Field(default_factory=list)
    cleaning_method: CleaningMethod = CleaningMethod.RULE_BASED_V1
