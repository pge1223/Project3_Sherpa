"""
Shared Domain Module
======================
embedding/과 retrieval/이 공통으로 참조하는 컨텍스트/예외를 둔다.
"""

from ai.rag.domain.schemas import (
    IndexingContext,
    CollectionConfigMismatchError,
    InvalidTopKError,
)
from ai.rag.domain.config import DEFAULT_COLLECTION_NAME

__all__ = [
    "IndexingContext",
    "CollectionConfigMismatchError",
    "InvalidTopKError",
    "DEFAULT_COLLECTION_NAME",
]
