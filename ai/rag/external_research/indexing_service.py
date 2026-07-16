"""
External Evidence Indexing Service (RAG-007)
===================================================
사전 수집된 외부 공개 통계·시장·정책 자료를 외부자료 전용 Chroma 컬렉션에 색인한다.
기존 KUREEmbedder를 그대로 재사용하며(embed_query 1건씩 임베딩 — ai.rag.similar_cases와
동일한 이유로 ChunkingResult 기반 배치 임베딩은 쓰지 않는다), 새 임베딩 모델을 만들지
않는다.
"""

import logging
from typing import Optional, Protocol, Sequence

from pydantic import BaseModel, Field

from ai.rag.external_research.exceptions import ExternalEvidenceIndexingError
from ai.rag.external_research.repository import ExternalEvidenceRepository
from ai.rag.external_research.schemas import ExternalEvidenceDocument
from ai.rag.external_research.source_validator import validate_source_metadata

logger = logging.getLogger(__name__)


class EmbedderLike(Protocol):
    """KUREEmbedder.embed_query()와 동일한 시그니처만 요구하는 최소 인터페이스."""

    def embed_query(self, query: str) -> list[float]:
        ...


class ExternalEvidenceIndexingSummary(BaseModel):
    """ExternalEvidenceIndexingService.index_evidence()의 반환값."""

    collection_name: str
    total_input_count: int
    indexed_count: int
    skipped_count: int
    warnings: list[str] = Field(default_factory=list)


class ExternalEvidenceIndexingService:
    def __init__(self, repository: ExternalEvidenceRepository, embedder: EmbedderLike):
        self._repository = repository
        self._embedder = embedder

    def index_evidence(
        self,
        documents: Sequence[ExternalEvidenceDocument],
        *,
        trace_id: Optional[str] = None,
    ) -> ExternalEvidenceIndexingSummary:
        """외부자료 청크 목록을 색인한다. 개별 자료가 유효하지 않으면(출처 누락, 빈
        content 등) 그 항목만 건너뛰고 warning을 남긴다 — 배치 전체를 실패시키지 않는다.
        Chroma 접근 자체가 불가능한 경우에만 ExternalEvidenceIndexingError를 던진다."""
        logger.info(
            "[EXTERNAL_EVIDENCE_INDEX_START] trace_id=%s total_input_count=%d",
            trace_id,
            len(documents),
        )

        warnings: list[str] = []
        indexed_count = 0
        skipped_count = 0

        for document in documents:
            content = document.content.strip() if document.content else ""
            if not content:
                skipped_count += 1
                warnings.append(
                    f"source_id={document.source_id} chunk_id={document.chunk_id}: content가 비어 있어 건너뜁니다."
                )
                continue

            verified, reasons = validate_source_metadata(
                {
                    "source_url": document.source_url,
                    "publisher": document.publisher,
                    "document_id": document.document_id,
                    "chunk_id": document.chunk_id,
                    "evidence_type": document.evidence_type.value,
                    "reference_date": document.reference_date,
                    "published_at": document.published_at,
                    "retrieved_at": document.retrieved_at,
                },
                content=content,
            )
            if not verified:
                skipped_count += 1
                warnings.append(
                    f"source_id={document.source_id} chunk_id={document.chunk_id}: "
                    f"출처 검증 실패로 건너뜁니다 ({', '.join(reasons)})."
                )
                continue

            try:
                embedding = self._embedder.embed_query(content)
                self._repository.upsert_evidence_chunk(document, embedding)
            except ExternalEvidenceIndexingError:
                raise
            except Exception as exc:
                logger.warning(
                    "[EXTERNAL_EVIDENCE_INDEX_FAILED] trace_id=%s source_id=%s chunk_id=%s error_code=%s",
                    trace_id,
                    document.source_id,
                    document.chunk_id,
                    type(exc).__name__,
                )
                raise ExternalEvidenceIndexingError(
                    f"source_id={document.source_id} chunk_id={document.chunk_id} 색인 중 오류: {exc}"
                ) from exc

            indexed_count += 1

        summary = ExternalEvidenceIndexingSummary(
            collection_name=self._repository.collection_name,
            total_input_count=len(documents),
            indexed_count=indexed_count,
            skipped_count=skipped_count,
            warnings=warnings,
        )

        logger.info(
            "[EXTERNAL_EVIDENCE_INDEX_COMPLETE] trace_id=%s indexed_count=%d skipped_count=%d",
            trace_id,
            indexed_count,
            skipped_count,
        )
        return summary


__all__ = ["ExternalEvidenceIndexingService", "ExternalEvidenceIndexingSummary", "EmbedderLike"]
