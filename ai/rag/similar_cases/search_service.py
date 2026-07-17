"""
Similar Case Search Service (RAG-006)
===========================================
문서 요약·도메인·평가 항목으로 사례 전용 컬렉션을 검색하고, 청크 단위 결과를
case_id 기준으로 집계해 사례 단위 Top-K를 반환한다. LangGraph나 ai.meeting.graph에
의존하지 않으며 단독으로 생성/호출할 수 있다.

유사 사례는 항상 참고 자료다 — 이 서비스는 RAG-005(근거 충족도)나 확정적 평가 점수를
직접 만들지 않는다(SimilarCaseResult.reference_only=True로 명시).
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Optional, Sequence

from ai.rag.similar_cases.comparison_service import (
    CaseAggregate,
    ComparisonOutcome,
    LLMCall,
    SupportingChunk,
    compare_case,
)
from ai.rag.similar_cases.config import SimilarCaseConfig
from ai.rag.similar_cases.exceptions import SimilarCaseSearchError
from ai.rag.similar_cases.indexing_service import EmbedderLike
from ai.rag.similar_cases.repository import CaseChunkHit, SimilarCaseRepository
from ai.rag.similar_cases.schemas import (
    ComparisonMode,
    SimilarCaseEvidence,
    SimilarCaseResult,
    SimilarCaseSearchRequest,
    SimilarCaseSearchResponse,
    SimilarCaseType,
)

logger = logging.getLogger(__name__)

_EMPTY_OUTCOME = ComparisonOutcome([], [], [], [], used_llm=False)


def build_similar_case_query(
    *,
    document_summary: str,
    domain: str,
    evaluation_criteria: Sequence[str],
) -> str:
    """문서 요약 전체를 통째로 검색 질의로 쓰지 않고, 도메인/평가 항목/요약을 조합해
    질의를 만든다. 순수 함수라 단위 테스트하기 쉽다."""
    criteria_text = ", ".join(evaluation_criteria)
    return f"도메인: {domain}\n평가 항목: {criteria_text}\n문서 요약: {document_summary}"


def _is_finite_score(value: Optional[float]) -> bool:
    return value is not None and not math.isnan(value) and not math.isinf(value)


@dataclass
class _CaseAccumulator:
    hits: list[CaseChunkHit] = field(default_factory=list)
    max_score: float = 0.0


class SimilarCaseSearchService:
    """RAG-003 검색과 완전히 분리된 사례 전용 검색 서비스. repository/embedder를
    생성자로 주입받으며, 새 Chroma client나 임베딩 모델을 내부에서 만들지 않는다."""

    def __init__(
        self,
        repository: SimilarCaseRepository,
        embedder: EmbedderLike,
        *,
        config: Optional[SimilarCaseConfig] = None,
        llm_call: Optional[LLMCall] = None,
    ):
        self._repository = repository
        self._embedder = embedder
        self._config = config or SimilarCaseConfig()
        self._llm_call = llm_call

    def search(self, request: SimilarCaseSearchRequest) -> SimilarCaseSearchResponse:
        top_k = min(request.top_k, self._config.max_top_k)
        min_score = request.min_score if request.min_score is not None else self._config.min_score
        candidate_k = top_k * self._config.candidate_k_multiplier

        query_text = build_similar_case_query(
            document_summary=request.document_summary,
            domain=request.domain,
            evaluation_criteria=request.evaluation_criteria,
        )

        logger.info(
            "[SIMILAR_CASE_SEARCH_START] trace_id=%s domain=%s criteria_count=%d top_k=%d",
            request.trace_id,
            request.domain,
            len(request.evaluation_criteria),
            top_k,
        )

        warnings: list[str] = []
        try:
            query_embedding = self._embedder.embed_query(query_text)
            hits = self._repository.search(query_embedding, domain=request.domain, top_k=candidate_k)

            if not hits and self._config.domain_filter_fallback_to_all:
                hits = self._repository.search(query_embedding, domain=None, top_k=candidate_k)
                if hits:
                    warnings.append(
                        f"도메인 '{request.domain}'에 해당하는 사례를 찾지 못해 전체 사례에서 검색했습니다."
                    )
        except Exception as exc:
            logger.warning(
                "[SIMILAR_CASE_SEARCH_FAILED] trace_id=%s domain=%s error_code=%s",
                request.trace_id,
                request.domain,
                type(exc).__name__,
            )
            raise SimilarCaseSearchError(f"유사 사례 검색 중 오류가 발생했습니다: {exc}") from exc

        valid_hits = self._filter_and_dedupe(hits, min_score)
        accumulators = self._aggregate_by_case(valid_hits, warnings)
        top_entries = sorted(accumulators.items(), key=lambda item: item[1].max_score, reverse=True)[:top_k]

        if not top_entries:
            logger.info(
                "[SIMILAR_CASE_SEARCH_EMPTY] trace_id=%s domain=%s candidate_count=%d",
                request.trace_id,
                request.domain,
                len(hits),
            )
            return SimilarCaseSearchResponse(
                results=[],
                total_results=0,
                has_rejected_cases=False,
                comparison_mode=ComparisonMode.SELECTED_CASE_GAP,
                query_text=query_text,
                trace_id=request.trace_id,
                warnings=warnings + ["현재 조건과 유사한 공개 사례를 찾지 못했습니다."],
            )

        results = [self._build_result(request, accumulator) for _, accumulator in top_entries]

        has_rejected = any(r.case_type == SimilarCaseType.REJECTED_CASE for r in results)
        comparison_mode = (
            ComparisonMode.SELECTED_AND_REJECTED_CASES if has_rejected else ComparisonMode.SELECTED_CASE_GAP
        )
        if not has_rejected:
            warnings.append("탈락 사례 데이터가 없어 선정 사례와 비교한 부족 항목으로 표시했습니다.")

        response = SimilarCaseSearchResponse(
            results=results,
            total_results=len(results),
            has_rejected_cases=has_rejected,
            comparison_mode=comparison_mode,
            query_text=query_text,
            trace_id=request.trace_id,
            warnings=warnings,
        )

        logger.info(
            "[SIMILAR_CASE_SEARCH_COMPLETE] trace_id=%s domain=%s candidate_count=%d "
            "result_count=%d comparison_mode=%s",
            request.trace_id,
            request.domain,
            len(hits),
            len(results),
            comparison_mode.value,
        )
        return response

    @staticmethod
    def _filter_and_dedupe(hits: list[CaseChunkHit], min_score: float) -> list[CaseChunkHit]:
        seen: set[tuple[str, str]] = set()
        filtered: list[CaseChunkHit] = []
        for hit in hits:
            if not _is_finite_score(hit.score):
                continue
            if hit.score < min_score:
                continue
            key = (hit.document_id, hit.chunk_id)
            if key in seen:
                continue
            seen.add(key)
            filtered.append(hit)
        return filtered

    @staticmethod
    def _aggregate_by_case(
        hits: list[CaseChunkHit], warnings: list[str]
    ) -> dict[str, _CaseAccumulator]:
        """청크를 case_id 기준으로 묶는다. 출처(source_name/source_url)가 없는 사례는
        정상 결과로 반환하지 않고 건너뛴다(섹션 18)."""
        accumulators: dict[str, _CaseAccumulator] = {}
        skipped_case_ids: set[str] = set()
        for hit in hits:
            case_id = hit.metadata.get("case_id")
            source_name = hit.metadata.get("source_name")
            source_url = hit.metadata.get("source_url")
            if not case_id or not source_name or not source_url:
                if case_id and case_id not in skipped_case_ids:
                    skipped_case_ids.add(case_id)
                continue
            entry = accumulators.setdefault(case_id, _CaseAccumulator())
            entry.hits.append(hit)
            entry.max_score = max(entry.max_score, hit.score)

        if skipped_case_ids:
            warnings.append(
                f"출처 정보가 없는 사례 {len(skipped_case_ids)}건을 결과에서 제외했습니다."
            )
        return accumulators

    def _build_result(self, request: SimilarCaseSearchRequest, accumulator: _CaseAccumulator) -> SimilarCaseResult:
        sorted_hits = sorted(accumulator.hits, key=lambda h: h.score, reverse=True)
        top_hits = sorted_hits[: self._config.max_evidence_per_case]
        metadata = sorted_hits[0].metadata

        evaluation_criteria: list[str] = metadata.get("evaluation_criteria") or []
        case_criteria_norm = {c.strip().lower() for c in evaluation_criteria}
        matched_criteria = [
            criterion for criterion in request.evaluation_criteria
            if criterion.strip().lower() in case_criteria_norm
        ]

        case_aggregate = CaseAggregate(
            case_id=metadata.get("case_id", ""),
            title=metadata.get("title", ""),
            case_type=SimilarCaseType(metadata.get("case_type")),
            domain=metadata.get("domain", ""),
            evaluation_criteria=evaluation_criteria,
            supporting_chunks=[
                SupportingChunk(
                    document_id=hit.document_id,
                    chunk_id=hit.chunk_id,
                    content=hit.content,
                    page=hit.metadata.get("page"),
                    section=hit.metadata.get("section"),
                    score=hit.score,
                )
                for hit in top_hits
            ],
        )

        outcome = compare_case(request, case_aggregate, llm_call=self._llm_call) or _EMPTY_OUTCOME

        evidence = [
            SimilarCaseEvidence(
                document_id=hit.document_id,
                chunk_id=hit.chunk_id,
                page=hit.metadata.get("page"),
                section=hit.metadata.get("section"),
                quote=hit.content,
                similarity_score=hit.score,
            )
            for hit in top_hits
        ]

        return SimilarCaseResult(
            case_id=case_aggregate.case_id,
            title=case_aggregate.title,
            case_type=case_aggregate.case_type,
            domain=case_aggregate.domain,
            source_name=metadata.get("source_name", ""),
            source_url=metadata.get("source_url", ""),
            similarity_score=accumulator.max_score,
            matched_criteria=matched_criteria,
            similarity_reasons=outcome.similarity_reasons,
            common_points=outcome.common_points,
            different_points=outcome.different_points,
            current_document_gaps=outcome.current_document_gaps,
            evidence=evidence,
        )


__all__ = ["SimilarCaseSearchService", "build_similar_case_query"]
