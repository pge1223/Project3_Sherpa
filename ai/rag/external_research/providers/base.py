"""
External Research Provider Protocol (RAG-007)
====================================================
검색 소스(사전 수집 Chroma 데이터셋, 공공데이터 API 등)를 provider로 분리한다.
search_service는 이 Protocol만 알고, 실제 provider 구현(Chroma든 HTTP든)에는
의존하지 않는다.
"""

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

from ai.rag.external_research.schemas import ExternalEvidenceType, ExternalResearchRequest


@dataclass(frozen=True)
class ExternalEvidenceCandidate:
    """provider가 반환하는 랭킹 이전 단계의 외부자료 후보 1건.

    ExternalEvidenceDocument(색인 입력)/ExternalEvidenceResult(최종 결과)와 필드가
    비슷하지만 별도 타입이다 — 이 타입은 provider와 search_service 사이의 내부
    계약이며, verified_source/semantic_score/retrieval_source처럼 최종 스키마에는
    없는 처리 중간 상태를 담는다."""

    source_id: str
    document_id: str
    chunk_id: str

    title: str
    evidence_type: ExternalEvidenceType

    publisher: str
    source_url: str

    domain: str
    evaluation_criteria: list[str] = field(default_factory=list)
    supported_roles: list[str] = field(default_factory=list)

    content: str = ""

    reference_date: Optional[str] = None
    published_at: Optional[str] = None
    retrieved_at: Optional[str] = None

    region: Optional[str] = None
    period: Optional[str] = None

    metric_name: Optional[str] = None
    metric_value: Optional[float | str] = None
    metric_unit: Optional[str] = None

    page: Optional[int] = None
    section: Optional[str] = None

    metadata: dict[str, Any] = field(default_factory=dict)

    semantic_score: Optional[float] = None
    verified_source: bool = False
    retrieval_source: str = "unknown"


class ExternalResearchProvider(Protocol):
    """검색 provider의 공통 인터페이스. 실제 네트워크/Chroma 호출 세부사항은
    구현체(DatasetProvider/PublicApiProvider)에 캡슐화된다."""

    @property
    def name(self) -> str:
        ...

    def search(
        self,
        request: ExternalResearchRequest,
        query_text: str,
    ) -> list[ExternalEvidenceCandidate]:
        ...


__all__ = ["ExternalEvidenceCandidate", "ExternalResearchProvider"]
