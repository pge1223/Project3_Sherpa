"""
Similar Case Chroma Repository (RAG-006)
==============================================
공개 성공 사례 전용 Chroma 컬렉션에 접근하는 저장소. 사용자 프로젝트 문서 컬렉션
(ai.rag.retrieval.chroma_store.ChromaVectorStore, 기본 컬렉션명 project_documents_kure_v1)과는
완전히 분리된 별도 컬렉션을 쓴다 — project_id 개념이 없고 case_id/domain 기준으로
필터링한다. client(chromadb.ClientAPI)는 생성자 주입이며, 이 저장소는 로컬
PersistentClient든 NCP HttpClient든 특정 client 구현에 결합되지 않는다
(ai.rag.retrieval.chroma_store.ChromaVectorStore와 동일한 패턴).
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import chromadb

from ai.rag.retrieval.metadata import restore_metadata, sanitize_metadata_for_chroma
from ai.rag.similar_cases.exceptions import SimilarCaseCollectionUnavailableError
from ai.rag.similar_cases.schemas import SimilarCaseDocument

logger = logging.getLogger(__name__)

_DISTANCE_METRIC = "cosine"
_SCHEMA_VERSION = "similar_cases_v1"

# sanitize_metadata_for_chroma()는 str/int/float/bool이 아닌 값(list 포함)을 모두
# JSON 문자열로 직렬화한다. ai.rag.retrieval.metadata.restore_metadata()는
# source_block_ids/source_block_orders만 다시 list로 복원하므로, evaluation_criteria는
# 이 저장소에서 직접 복원한다.
_CASE_JSON_LIST_FIELDS: frozenset[str] = frozenset({"evaluation_criteria"})


def build_case_record_id(document_id: str, chunk_id: str) -> str:
    """사례 컬렉션의 Chroma record ID. 별도 컬렉션에 저장되므로 project_id 접두사가 필요 없다."""
    return f"{document_id}::{chunk_id}"


def _restore_case_metadata(raw_metadata: Optional[dict]) -> dict:
    restored = restore_metadata(raw_metadata or {})
    for key in _CASE_JSON_LIST_FIELDS:
        value = restored.get(key)
        if isinstance(value, str):
            try:
                restored[key] = json.loads(value)
            except json.JSONDecodeError:
                restored[key] = []
    return restored


@dataclass(frozen=True)
class CaseChunkHit:
    """Chroma 검색 결과 1건(청크 단위, 아직 사례 단위로 집계되지 않음)."""

    record_id: str
    document_id: str
    chunk_id: str
    content: str
    distance: Optional[float]
    score: Optional[float]
    metadata: dict = field(default_factory=dict)


class SimilarCaseRepository:
    """사례 전용 Chroma 컬렉션에 대한 upsert/search."""

    def __init__(
        self,
        client: chromadb.ClientAPI,
        collection_name: str,
        embedding_model: str,
        embedding_dimension: int,
        embedding_version: str,
    ):
        self._client = client
        self._collection_name = collection_name
        self._embedding_model = embedding_model
        self._embedding_dimension = embedding_dimension
        self._embedding_version = embedding_version
        self._collection = self._get_or_create_collection()

    @property
    def collection_name(self) -> str:
        return self._collection_name

    def _get_or_create_collection(self):
        try:
            collection = self._client.get_or_create_collection(
                name=self._collection_name,
                metadata={
                    "hnsw:space": _DISTANCE_METRIC,
                    "embedding_model": self._embedding_model,
                    "embedding_dimension": self._embedding_dimension,
                    "embedding_version": self._embedding_version,
                    "schema_version": _SCHEMA_VERSION,
                },
            )
        except Exception as exc:  # pragma: no cover - chromadb 자체 연결 실패 등 방어적 처리
            raise SimilarCaseCollectionUnavailableError(
                f"사례 전용 컬렉션 '{self._collection_name}'을 열 수 없습니다: {exc}"
            ) from exc

        existing = collection.metadata or {}
        for key, current in (
            ("embedding_model", self._embedding_model),
            ("embedding_dimension", self._embedding_dimension),
            ("embedding_version", self._embedding_version),
        ):
            existing_value = existing.get(key)
            if existing_value is not None and existing_value != current:
                raise SimilarCaseCollectionUnavailableError(
                    f"컬렉션 '{self._collection_name}'의 기존 {key}('{existing_value}')가 "
                    f"현재 설정('{current}')과 달라 같은 컬렉션에 섞어 저장할 수 없습니다."
                )
        return collection

    def upsert_case_chunk(self, case: SimilarCaseDocument, embedding: list[float]) -> str:
        """사례 청크 1건을 upsert한다. 동일 (document_id, chunk_id)는 같은 record를 덮어써
        중복 색인되지 않는다. 반환값은 upsert된 record_id."""
        record_id = build_case_record_id(case.document_id, case.chunk_id)
        raw_metadata: dict[str, Any] = {
            "case_id": case.case_id,
            "title": case.title,
            "case_type": case.case_type,
            "domain": case.domain,
            "evaluation_criteria": case.evaluation_criteria,
            "source_name": case.source_name,
            "source_url": case.source_url,
            "document_id": case.document_id,
            "chunk_id": case.chunk_id,
            "page": case.page,
            "section": case.section,
            "published_at": case.published_at,
        }
        # 호출자 metadata는 알려진 키를 덮어쓰지 않는 범위에서만 병합한다.
        for key, value in case.metadata.items():
            raw_metadata.setdefault(key, value)

        self._collection.upsert(
            ids=[record_id],
            embeddings=[embedding],
            documents=[case.content],
            metadatas=[sanitize_metadata_for_chroma(raw_metadata)],
        )
        return record_id

    def search(
        self,
        query_embedding: list[float],
        *,
        domain: Optional[str] = None,
        top_k: int,
    ) -> list[CaseChunkHit]:
        """청크 단위 검색 결과를 반환한다(사례 단위 집계는 search_service의 책임).
        domain이 주어지면 metadata.domain == domain으로 필터링한다."""
        where = {"domain": domain} if domain else None
        raw = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        ids = raw["ids"][0] if raw.get("ids") else []
        documents = raw["documents"][0] if raw.get("documents") else [None] * len(ids)
        metadatas = raw["metadatas"][0] if raw.get("metadatas") else [{}] * len(ids)
        distances = raw["distances"][0] if raw.get("distances") else [None] * len(ids)

        hits: list[CaseChunkHit] = []
        for record_id, content, raw_metadata, distance in zip(ids, documents, metadatas, distances):
            metadata = _restore_case_metadata(raw_metadata)
            score = self._distance_to_score(distance)
            hits.append(
                CaseChunkHit(
                    record_id=record_id,
                    document_id=metadata.get("document_id", ""),
                    chunk_id=metadata.get("chunk_id", record_id),
                    content=content or "",
                    distance=distance,
                    score=score,
                    metadata=metadata,
                )
            )
        return hits

    @staticmethod
    def _distance_to_score(distance: Optional[float]) -> Optional[float]:
        """hnsw:space='cosine' 컬렉션에서 Chroma distance = 1 - cosine_similarity
        (ai.rag.retrieval.chroma_store.ChromaVectorStore._distance_to_score와 동일 정의)."""
        if distance is None:
            return None
        return 1.0 - distance

    def count(self) -> int:
        return self._collection.count()


__all__ = ["SimilarCaseRepository", "CaseChunkHit", "build_case_record_id"]
