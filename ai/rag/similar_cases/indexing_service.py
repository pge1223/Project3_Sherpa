"""
Similar Case Indexing Service (RAG-006)
=============================================
공개 사례 데이터를 사례 전용 Chroma 컬렉션에 색인한다. 기존 KUREEmbedder를 그대로
재사용하며(embed_query 1건씩 임베딩 — ChunkingResult 기반 배치 임베딩은 문서 파싱
파이프라인 전용이라 여기서는 맞지 않음), 새 임베딩 모델을 만들지 않는다.
"""

import logging
from typing import Optional, Protocol, Sequence

from pydantic import BaseModel, Field

from ai.rag.similar_cases.exceptions import SimilarCaseIndexingError
from ai.rag.similar_cases.repository import SimilarCaseRepository
from ai.rag.similar_cases.schemas import SimilarCaseDocument

logger = logging.getLogger(__name__)


class EmbedderLike(Protocol):
    """KUREEmbedder.embed_query()와 동일한 시그니처만 요구하는 최소 인터페이스.
    실제 KUREEmbedder 인스턴스뿐 아니라 테스트용 fake도 그대로 주입할 수 있다."""

    def embed_query(self, query: str) -> list[float]:
        ...


class SimilarCaseIndexingSummary(BaseModel):
    """SimilarCaseIndexingService.index_cases()의 반환값."""

    collection_name: str
    total_input_count: int
    indexed_count: int
    skipped_count: int
    warnings: list[str] = Field(default_factory=list)


class SimilarCaseIndexingService:
    def __init__(self, repository: SimilarCaseRepository, embedder: EmbedderLike):
        self._repository = repository
        self._embedder = embedder

    def index_cases(
        self,
        cases: Sequence[SimilarCaseDocument],
        *,
        trace_id: Optional[str] = None,
    ) -> SimilarCaseIndexingSummary:
        """사례 청크 목록을 색인한다. 개별 사례가 유효하지 않으면(빈 content 등) 그 항목만
        건너뛰고 warning을 남긴다 — 배치 전체를 실패시키지 않는다. Chroma 접근 자체가
        불가능한 경우에만 SimilarCaseIndexingError를 던진다(SimilarCaseRepository 생성
        시점에 이미 검증되므로 보통 여기서는 upsert 단계 실패만 해당)."""
        logger.info(
            "[SIMILAR_CASE_INDEX_START] trace_id=%s total_input_count=%d",
            trace_id,
            len(cases),
        )

        warnings: list[str] = []
        indexed_count = 0
        skipped_count = 0

        for case in cases:
            content = case.content.strip()
            if not content:
                skipped_count += 1
                warnings.append(f"case_id={case.case_id} chunk_id={case.chunk_id}: content가 비어 있어 건너뜁니다.")
                continue

            try:
                embedding = self._embedder.embed_query(content)
                self._repository.upsert_case_chunk(case, embedding)
            except SimilarCaseIndexingError:
                raise
            except Exception as exc:
                logger.warning(
                    "[SIMILAR_CASE_INDEX_FAILED] trace_id=%s case_id=%s chunk_id=%s error_code=%s",
                    trace_id,
                    case.case_id,
                    case.chunk_id,
                    type(exc).__name__,
                )
                raise SimilarCaseIndexingError(
                    f"case_id={case.case_id} chunk_id={case.chunk_id} 색인 중 오류: {exc}"
                ) from exc

            indexed_count += 1

        summary = SimilarCaseIndexingSummary(
            collection_name=self._repository.collection_name,
            total_input_count=len(cases),
            indexed_count=indexed_count,
            skipped_count=skipped_count,
            warnings=warnings,
        )

        logger.info(
            "[SIMILAR_CASE_INDEX_COMPLETE] trace_id=%s indexed_count=%d skipped_count=%d",
            trace_id,
            indexed_count,
            skipped_count,
        )
        return summary


__all__ = ["SimilarCaseIndexingService", "SimilarCaseIndexingSummary", "EmbedderLike"]
