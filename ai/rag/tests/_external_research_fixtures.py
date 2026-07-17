"""
Shared Test Helpers for RAG-007 (External Market/Policy Research)
========================================================================
pytest가 테스트 모듈로 수집하지 않도록 파일명이 test_로 시작하지 않는다.
"""

import hashlib
from typing import Optional


class FakeEvidenceEmbedder:
    """실제 KURE-v1을 로딩하지 않는 결정적 가짜 임베더. ai.rag.tests._similar_case_fixtures
    의 FakeCaseEmbedder와 동일한 패턴 — 등록된 문자열은 정확한 벡터를, 그 외는 해시 기반
    fallback 벡터를 반환한다."""

    def __init__(self, dimension: int = 4, overrides: Optional[dict[str, list[float]]] = None):
        self._dimension = dimension
        self._overrides = overrides or {}

    @property
    def model_name(self) -> str:
        return "fake-external-research-embedder"

    @property
    def embedding_dimension(self) -> int:
        return self._dimension

    def embed_query(self, query: str) -> list[float]:
        if query in self._overrides:
            return list(self._overrides[query])
        digest = hashlib.sha256(query.encode("utf-8")).digest()
        raw = [b / 255.0 for b in digest[: self._dimension]]
        norm = sum(v * v for v in raw) ** 0.5
        if norm == 0:
            return raw
        return [v / norm for v in raw]
