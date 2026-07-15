"""
Embedding Configuration Defaults
==================================
"""

DEFAULT_MODEL_NAME: str = "nlpai-lab/KURE-v1"
DEFAULT_DEVICE: str = "cpu"  # "cpu" | "cuda" | "auto"
DEFAULT_BATCH_SIZE: int = 32
DEFAULT_NORMALIZE_EMBEDDINGS: bool = True
DEFAULT_SHOW_PROGRESS: bool = False
DEFAULT_MODEL_CACHE_DIR: str | None = None  # None이면 huggingface_hub 기본 캐시 경로(~/.cache/huggingface) 사용
DEFAULT_TRUST_REMOTE_CODE: bool = False  # KURE-v1 모델 카드 기준 커스텀 코드 불필요 (smoke test에서 확인)

EMBEDDING_VERSION: str = "embedding_v1"
