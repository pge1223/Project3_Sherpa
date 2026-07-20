"""
Domain Classification (DOM-001, 공고문/평가 대상 문서 도메인 자동 분류)
=========================================================================
청킹 결과 또는 정제된 텍스트를 받아 competition/government_support/startup 중
하나로 분류하고, 확신이 낮으면 unknown으로 남긴다. 분류 결과를 project에 실제로
반영할지는 backend 몫이며, 사용자의 DOM-002 수동 변경 흐름을 대체하지 않는다.
"""

from ai.rag.domain_classification.config import DomainClassificationConfig
from ai.rag.domain_classification.schemas import (
    KNOWN_DOMAIN_LABELS,
    DomainClassificationRequest,
    DomainClassificationResult,
    DomainLabel,
)
from ai.rag.domain_classification.service import (
    DomainClassificationError,
    DomainClassificationService,
    LLMCall,
)

__all__ = [
    "DomainClassificationConfig",
    "KNOWN_DOMAIN_LABELS",
    "DomainClassificationRequest",
    "DomainClassificationResult",
    "DomainLabel",
    "DomainClassificationError",
    "DomainClassificationService",
    "LLMCall",
]
