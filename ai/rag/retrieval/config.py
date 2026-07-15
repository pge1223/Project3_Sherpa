"""
Retrieval (Chroma Vector Store) Configuration Defaults
=========================================================
"""

from ai.rag.domain.config import DEFAULT_COLLECTION_NAME

DISTANCE_METRIC: str = "cosine"  # chromadb hnsw:space
RETRIEVAL_SCHEMA_VERSION: str = "retrieval_v1"
DEFAULT_TOP_K: int = 5

__all__ = ["DEFAULT_COLLECTION_NAME", "DISTANCE_METRIC", "RETRIEVAL_SCHEMA_VERSION", "DEFAULT_TOP_K"]
