"""
Evidence Linker
==================
평가 의견 1건과 검색 결과 목록(RAG-002 SearchResult 또는 RAG-003 RoleSearchResult)을
받아 LinkedEvaluation을 만든다. 새 검색이나 LLM 호출 없음 — 이미 받은 결과만 사용한다.
"""

from typing import Any, Optional

from ai.rag.evidence_linking.config import EvidenceLinkingConfig
from ai.rag.evidence_linking.metadata import (
    extract_content_kind,
    extract_document_title,
    extract_page_number,
    extract_section_title,
)
from ai.rag.evidence_linking.quote_extractor import extract_quote
from ai.rag.evidence_linking.relevance import is_relevant_candidate
from ai.rag.evidence_linking.schemas import EvidenceSource, LinkedEvaluation


def resolve_score(result: Any) -> float:
    """RoleSearchResult.final_score 우선, 없으면 semantic_score/score, 그것도 없으면 0.0."""
    final_score = getattr(result, "final_score", None)
    if final_score is not None:
        return final_score

    semantic_score = getattr(result, "semantic_score", None)
    if semantic_score is not None:
        return semantic_score

    score = getattr(result, "score", None)
    if score is not None:
        return score

    return 0.0


def _resolve_semantic_score(result: Any) -> Optional[float]:
    semantic_score = getattr(result, "semantic_score", None)
    if semantic_score is not None:
        return semantic_score
    return getattr(result, "score", None)


def _is_valid_candidate(result: Any) -> bool:
    document_id = getattr(result, "document_id", None)
    chunk_id = getattr(result, "chunk_id", None)
    content = getattr(result, "content", None)
    if not document_id or not chunk_id:
        return False
    if not content or not content.strip():
        return False
    return True


def _select_candidates(
    opinion: str,
    search_results: list[Any],
    config: EvidenceLinkingConfig,
    max_evidence: int,
    role_keywords: Optional[list[str]] = None,
) -> list[Any]:
    """유효성 검증 -> 최소 점수 필터 -> 의견-청크 관련성 검사 ->
    chunk_id 중복 제거(최고점 유지) -> 점수 내림차순 -> 상한.

    검색 점수가 높아도 평가 의견과 무관한 청크(예: 일정 관련 의견에 시장 분석 청크)는
    관련성 검사에서 제외되어 근거로 선택되지 않는다."""
    best_by_chunk: dict[str, tuple[float, Any]] = {}
    for result in search_results or []:
        if not _is_valid_candidate(result):
            continue
        score = resolve_score(result)
        if score < config.min_evidence_score:
            continue
        if config.require_text_relevance:
            metadata = result.metadata or {}
            relevant = is_relevant_candidate(
                opinion=opinion,
                content=result.content,
                section_title=extract_section_title(metadata),
                document_title=extract_document_title(metadata),
                role_keywords=role_keywords,
                config=config,
            )
            if not relevant:
                continue
        chunk_id = result.chunk_id
        existing = best_by_chunk.get(chunk_id)
        if existing is None or score > existing[0]:
            best_by_chunk[chunk_id] = (score, result)

    ordered = sorted(best_by_chunk.values(), key=lambda pair: pair[0], reverse=True)
    return [result for _, result in ordered[:max_evidence]]


def build_linked_evaluation(
    opinion: str,
    search_results: list[Any],
    config: EvidenceLinkingConfig,
    role_id: Optional[str] = None,
    role_name: Optional[str] = None,
    role_keywords: Optional[list[str]] = None,
    max_evidence: Optional[int] = None,
) -> LinkedEvaluation:
    effective_max = max_evidence if max_evidence is not None else config.max_evidence

    selected = _select_candidates(opinion, search_results, config, effective_max, role_keywords)
    if not selected:
        return LinkedEvaluation(opinion=opinion, role_id=role_id, role_name=role_name, has_evidence=False, evidence=[])

    evidence: list[EvidenceSource] = []
    for result in selected:
        quote = extract_quote(result.content, opinion, config, role_keywords)
        if not quote:
            # content가 비어있지 않은 유효 후보에서만 여기 도달하므로 사실상 발생하지 않지만,
            # 방어적으로 근거 없는 항목을 만들지 않는다.
            continue
        metadata = result.metadata or {}
        evidence.append(EvidenceSource(
            document_id=result.document_id,
            chunk_id=result.chunk_id,
            document_title=extract_document_title(metadata),
            page_number=extract_page_number(metadata),
            section_title=extract_section_title(metadata),
            content_kind=extract_content_kind(metadata),
            quote=quote,
            semantic_score=_resolve_semantic_score(result),
            role_score=getattr(result, "role_score", None),
            final_score=getattr(result, "final_score", None),
        ))

    if not evidence:
        return LinkedEvaluation(opinion=opinion, role_id=role_id, role_name=role_name, has_evidence=False, evidence=[])

    return LinkedEvaluation(opinion=opinion, role_id=role_id, role_name=role_name, has_evidence=True, evidence=evidence)
