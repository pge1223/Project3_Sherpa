"""
Public API Provider (RAG-007)
===================================
실시간 공공데이터 API 검색용 provider. 섹션 5/25 원칙에 따라, 실제로 사용할 API가
아직 확정되지 않았고 인증키·이용약관·비용이 확인되지 않았으므로 이 클래스는
실제 HTTP 호출 코드를 담고 있지 않다 — provider 인터페이스와 오류 정규화, timeout
처리, mock 테스트까지만 구현한다.

실제로 승인된 공공데이터 API가 정해지면, 그 API를 감싸는 `fetch` 콜러블
(`PublicApiFetchFn`)을 만들어 이 클래스에 주입하면 된다. 이 파일 자체는 어떤
특정 API 엔드포인트나 키도 알지 못한다(하드코딩 금지 원칙).
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Callable, Optional

from ai.rag.external_research.config import PublicApiProviderConfig
from ai.rag.external_research.exceptions import (
    ExternalProviderTimeoutError,
    ExternalProviderUnavailableError,
)
from ai.rag.external_research.providers.base import ExternalEvidenceCandidate
from ai.rag.external_research.schemas import ExternalEvidenceType, ExternalResearchRequest
from ai.rag.external_research.source_validator import validate_source_metadata

logger = logging.getLogger(__name__)

# 실제 API 응답(호출자가 이미 정규화해 넘긴 dict 목록)을 받아오는 콜러블. 이 프로젝트는
# 어떤 구체적인 공공데이터 API도 구현하지 않는다 — 호출자가 승인된 API를 감싸 주입한다.
PublicApiFetchFn = Callable[[ExternalResearchRequest, str], list[dict]]


def _raw_to_candidate(raw: dict) -> Optional[ExternalEvidenceCandidate]:
    """fetch()가 반환한 원시 dict 1건을 후보로 변환한다. evidence_type을 확인할 수
    없으면(모르는 값이거나 없음) None을 반환해 결과에서 제외한다 — 자료 유형을
    임의로 추정하지 않는다."""
    evidence_type_raw = raw.get("evidence_type")
    if not evidence_type_raw:
        return None
    try:
        evidence_type = ExternalEvidenceType(evidence_type_raw)
    except ValueError:
        return None

    metadata_for_validation = {
        "source_url": raw.get("source_url"),
        "publisher": raw.get("publisher"),
        "document_id": raw.get("document_id"),
        "chunk_id": raw.get("chunk_id"),
        "evidence_type": evidence_type.value,
        "reference_date": raw.get("reference_date"),
        "published_at": raw.get("published_at"),
        "retrieved_at": raw.get("retrieved_at"),
    }
    verified, _reasons = validate_source_metadata(metadata_for_validation, content=raw.get("content", ""))

    return ExternalEvidenceCandidate(
        source_id=raw.get("source_id", ""),
        document_id=raw.get("document_id", ""),
        chunk_id=raw.get("chunk_id", ""),
        title=raw.get("title", ""),
        evidence_type=evidence_type,
        publisher=raw.get("publisher", ""),
        source_url=raw.get("source_url", ""),
        domain=raw.get("domain", ""),
        evaluation_criteria=raw.get("evaluation_criteria") or [],
        supported_roles=raw.get("supported_roles") or [],
        content=raw.get("content", ""),
        reference_date=raw.get("reference_date"),
        published_at=raw.get("published_at"),
        retrieved_at=raw.get("retrieved_at"),
        region=raw.get("region"),
        period=raw.get("period"),
        metric_name=raw.get("metric_name"),
        metric_value=raw.get("metric_value"),
        metric_unit=raw.get("metric_unit"),
        page=raw.get("page"),
        section=raw.get("section"),
        metadata=raw,
        # 외부 API가 자체 유사도 점수를 주지 않는 것이 일반적이므로 None으로 둔다 —
        # search_service의 랭킹 단계에서 None은 0.0(최저 semantic_score)으로 취급된다
        # (점수를 지어내지 않는다는 원칙).
        semantic_score=raw.get("semantic_score"),
        verified_source=verified,
        retrieval_source="public_api",
    )


class PublicApiProvider:
    """공공데이터 API provider. fetch가 주입되지 않았거나 enabled=False면 실제로
    아무것도 호출하지 않고 명확한 예외를 던진다 — 비어있는 결과를 조용히 반환해
    "검색했지만 없었다"처럼 보이게 만들지 않는다."""

    def __init__(
        self,
        *,
        fetch: Optional[PublicApiFetchFn] = None,
        config: Optional[PublicApiProviderConfig] = None,
        enabled: bool = False,
    ):
        self._fetch = fetch
        self._config = config or PublicApiProviderConfig()
        self._enabled = enabled

    @property
    def name(self) -> str:
        return "public_api"

    @property
    def enabled(self) -> bool:
        return self._enabled

    def search(self, request: ExternalResearchRequest, query_text: str) -> list[ExternalEvidenceCandidate]:
        if not self._enabled:
            raise ExternalProviderUnavailableError("PublicApiProvider가 비활성화되어 있습니다.")
        if self._fetch is None:
            raise ExternalProviderUnavailableError(
                "PublicApiProvider에 fetch 콜러블이 주입되지 않았습니다 — 실제 공공데이터 API가 "
                "확정되기 전까지는 이 provider를 호출할 수 없습니다."
            )

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self._fetch, request, query_text)
            try:
                raw_results = future.result(timeout=self._config.timeout_seconds)
            except FutureTimeoutError as exc:
                raise ExternalProviderTimeoutError(
                    f"공공데이터 API 호출이 timeout_seconds={self._config.timeout_seconds}초를 초과했습니다."
                ) from exc
            except (ExternalProviderTimeoutError, ExternalProviderUnavailableError):
                raise
            except Exception as exc:
                raise ExternalProviderUnavailableError(
                    f"공공데이터 API 호출 중 오류가 발생했습니다: {type(exc).__name__}"
                ) from exc

        candidates: list[ExternalEvidenceCandidate] = []
        for raw in list(raw_results)[: self._config.max_results]:
            candidate = _raw_to_candidate(raw)
            if candidate is not None:
                candidates.append(candidate)
        return candidates


__all__ = ["PublicApiProvider", "PublicApiFetchFn"]
