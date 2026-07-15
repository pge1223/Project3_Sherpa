"""
Deterministic Fake SentenceTransformer for Unit Tests
========================================================
실제 KURE-v1을 로딩하지 않고 ai.rag.embedding.kure_embedder.SentenceTransformer를
대체하는 결정적 가짜 모델. 같은 텍스트는 항상 같은 벡터를 반환하고, 서로 다른
텍스트는 서로 다른 벡터를 반환해 query/document 임베딩을 구분할 수 있다.
"""

import hashlib

import numpy as np

FAKE_EMBEDDING_DIMENSION = 8


class FakeSentenceTransformer:
    def __init__(self, model_name, device=None, cache_folder=None, trust_remote_code=False):
        self.model_name = model_name
        self.device = device

    def get_embedding_dimension(self) -> int:
        return FAKE_EMBEDDING_DIMENSION

    def encode(self, texts, batch_size=32, normalize_embeddings=True, show_progress_bar=False):
        vectors = [self._vector_for(text, normalize_embeddings) for text in texts]
        return np.array(vectors, dtype=np.float32)

    @staticmethod
    def _vector_for(text: str, normalize: bool) -> np.ndarray:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        seed = int.from_bytes(digest[:4], "big")
        rng = np.random.default_rng(seed)
        vector = rng.random(FAKE_EMBEDDING_DIMENSION).astype(np.float32)
        if normalize:
            norm = np.linalg.norm(vector)
            if norm > 0:
                vector = vector / norm
        return vector
