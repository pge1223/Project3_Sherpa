"""
Dataset Provider (RAG-007)
================================
사전 수집·색인된 외부자료 Chroma 컬렉션을 검색하는 1순위 provider(섹션 5). 새 Chroma
client나 임베딩 모델을 만들지 않고 생성자로 주입받은 ExternalEvidenceRepository/
KUREEmbedder(호환 객체)를 그대로 재사용한다.
"""

import logging
from typing import Optional

from ai.rag.external_research.config import ExternalResearchConfig
from ai.rag.external_research.exceptions import ExternalEvidenceSearchError
from ai.rag.external_research.indexing_service import EmbedderLike
from ai.rag.external_research.providers.base import ExternalEvidenceCandidate
from ai.rag.external_research.repository import ExternalEvidenceHit, ExternalEvidenceRepository
from ai.rag.external_research.schemas import ExternalResearchRequest
from ai.rag.external_research.source_validator import validate_source_metadata

logger = logging.getLogger(__name__)


def _hit_to_candidate(hit: ExternalEvidenceHit, *, retrieval_source: str) -> Optional[ExternalEvidenceCandidate]:
    metadata = hit.metadata
    evidence_type_raw = metadata.get("evidence_type")
    if not evidence_type_raw:
        return None
    from ai.rag.external_research.schemas import ExternalEvidenceType

    try:
        evidence_type = ExternalEvidenceType(evidence_type_raw)
    except ValueError:
        return None

    verified, _reasons = validate_source_metadata(metadata, content=hit.content)

    return ExternalEvidenceCandidate(
        source_id=hit.source_id,
        document_id=hit.document_id,
        chunk_id=hit.chunk_id,
        title=metadata.get("title", ""),
        evidence_type=evidence_type,
        publisher=metadata.get("publisher", ""),
        source_url=metadata.get("source_url", ""),
        domain=metadata.get("domain", ""),
        evaluation_criteria=metadata.get("evaluation_criteria") or [],
        supported_roles=metadata.get("supported_roles") or [],
        content=hit.content,
        reference_date=metadata.get("reference_date"),
        published_at=metadata.get("published_at"),
        retrieved_at=metadata.get("retrieved_at"),
        region=metadata.get("region"),
        period=metadata.get("period"),
        metric_name=metadata.get("metric_name"),
        metric_value=metadata.get("metric_value"),
        metric_unit=metadata.get("metric_unit"),
        page=metadata.get("page"),
        section=metadata.get("section"),
        metadata=metadata,
        semantic_score=hit.score,
        verified_source=verified,
        retrieval_source=retrieval_source,
    )


class DatasetProvider:
    """ExternalResearchProvider 구현체 — 사전 수집 Chroma 데이터셋 검색.

    도메인 필터 결과가 0건이고 config.domain_filter_fallback_to_all이 True면 도메인
    필터 없이 전체 컬렉션에서 다시 검색한다. Protocol이 search()의 반환 타입을
    list[ExternalEvidenceCandidate]로 고정하고 있어 fallback 발생 여부를 반환값에
    함께 실어 보낼 수 없으므로, 마지막 호출에서 fallback이 있었는지는
    `last_search_used_domain_fallback` 속성으로 노출한다 — search_service가 호출
    직후 이 값을 읽어 warning 문구를 만든다."""

    def __init__(
        self,
        repository: ExternalEvidenceRepository,
        embedder: EmbedderLike,
        *,
        config: Optional[ExternalResearchConfig] = None,
    ):
        self._repository = repository
        self._embedder = embedder
        self._config = config or ExternalResearchConfig()
        self.last_search_used_domain_fallback: bool = False

    @property
    def name(self) -> str:
        return "dataset"

    def search(self, request: ExternalResearchRequest, query_text: str) -> list[ExternalEvidenceCandidate]:
        self.last_search_used_domain_fallback = False
        top_k = min(request.top_k, self._config.max_top_k)
        candidate_k = top_k * self._config.candidate_k_multiplier

        try:
            query_embedding = self._embedder.embed_query(query_text)
            hits = self._repository.search(
                query_embedding,
                domain=request.domain,
                evidence_types=request.evidence_types,
                top_k=candidate_k,
            )
            if not hits and self._config.domain_filter_fallback_to_all:
                hits = self._repository.search(
                    query_embedding,
                    domain=None,
                    evidence_types=request.evidence_types,
                    top_k=candidate_k,
                )
                if hits:
                    self.last_search_used_domain_fallback = True
        except Exception as exc:
            raise ExternalEvidenceSearchError(f"외부자료 데이터셋 검색 중 오류가 발생했습니다: {exc}") from exc

        candidates: list[ExternalEvidenceCandidate] = []
        for hit in hits:
            candidate = _hit_to_candidate(hit, retrieval_source=self.name)
            if candidate is not None:
                candidates.append(candidate)
        return candidates


__all__ = ["DatasetProvider"]
