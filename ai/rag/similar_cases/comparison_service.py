"""
Similar Case Comparison (RAG-006)
=======================================
검색된 사례 청크와 현재 문서 요약·평가 항목만 사용해 유사 이유, 공통점, 차이점,
현재 문서 보완점을 만든다.

기본은 결정론적(규칙 기반) 생성이며, LLM은 완전히 선택 사항이다. 새 LLM 공급자나
클라이언트를 추가하지 않고, 호출자가 `str -> str` 콜러블(이 프로젝트의
ai.meeting.graph.llm.LLMCall과 같은 모양)을 직접 주입할 때만 사용한다 — RAG-006은
ai.meeting.graph에 의존하면 안 되므로 그 모듈의 타입을 import하지 않고 동일한 모양의
타입을 이 파일에서 독립적으로 정의한다.

LLM 호출이 실패하거나 출력을 신뢰할 수 없으면(JSON 파싱 실패, 필수 키 누락, 타입 불일치)
항상 결정론적 방식으로 fallback한다 — 비교 실패가 검색 결과 자체를 실패시키지 않는다.
검색 결과에 첨부되는 evidence(quote)는 항상 search_service가 실제 검색된 청크
원문에서 그대로 만들며, comparison_service/LLM이 evidence를 생성하지 않는다 —
그래서 "존재하지 않는 근거 참조" 문제가 구조적으로 발생하지 않는다.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

from ai.rag.evidence_linking.relevance import extract_keywords
from ai.rag.similar_cases.schemas import SimilarCaseSearchRequest, SimilarCaseType

logger = logging.getLogger(__name__)

# 프롬프트 문자열 하나를 받아 응답 문자열 하나를 반환하는 콜러블. 이 모듈은 이 타입의
# 구체 구현(OpenAI/Anthropic 등)을 만들지 않는다 — 호출자가 기존 LLM 추상화로 구현한
# 콜러블을 주입한다.
LLMCall = Callable[[str], str]

_MAX_REASONS = 4
_MAX_COMMON_POINTS = 4
_MAX_DIFFERENT_POINTS = 3
_MAX_GAPS = 3
_MAX_KEYWORDS_PER_CHUNK = 3


@dataclass(frozen=True)
class SupportingChunk:
    """비교에 사용할 사례 청크 1건 (search_service가 채워서 넘긴다)."""

    document_id: str
    chunk_id: str
    content: str
    page: Optional[int] = None
    section: Optional[str] = None
    score: Optional[float] = None


@dataclass(frozen=True)
class CaseAggregate:
    """사례 단위로 집계된 비교 입력."""

    case_id: str
    title: str
    case_type: SimilarCaseType
    domain: str
    evaluation_criteria: list[str] = field(default_factory=list)
    supporting_chunks: list[SupportingChunk] = field(default_factory=list)


@dataclass(frozen=True)
class ComparisonOutcome:
    similarity_reasons: list[str]
    common_points: list[str]
    different_points: list[str]
    current_document_gaps: list[str]
    used_llm: bool = False


def _normalize(text: str) -> str:
    return text.strip().lower()


def _cannot_confirm(subject: str) -> str:
    """"~없습니다"처럼 단정하지 않고, 확인하기 어렵다는 형태로만 표현한다."""
    return f"제공된 현재 문서 요약과 근거에서는 {subject} 관련 내용을 확인하기 어렵습니다."


def compare_case(
    request: SimilarCaseSearchRequest,
    case: CaseAggregate,
    *,
    llm_call: Optional[LLMCall] = None,
) -> ComparisonOutcome:
    """사례 1건에 대한 비교 결과를 만든다. llm_call이 주어지고 성공하면 그 결과를 쓰고,
    없거나 실패하면 규칙 기반 결과로 fallback한다. 이 함수 자체는 예외를 던지지 않는다
    (실패 시 무조건 규칙 기반 결과를 반환) — 호출자가 별도로 예외 처리를 할 필요가 없다."""
    if llm_call is not None:
        try:
            llm_outcome = _compare_with_llm(request, case, llm_call)
            if llm_outcome is not None:
                return llm_outcome
        except Exception as exc:
            logger.warning(
                "[SIMILAR_CASE_COMPARISON_FAILED] case_id=%s error_code=%s",
                case.case_id,
                type(exc).__name__,
            )
    return _compare_rule_based(request, case)


def _compare_rule_based(request: SimilarCaseSearchRequest, case: CaseAggregate) -> ComparisonOutcome:
    reasons: list[str] = []
    common: list[str] = []
    different: list[str] = []
    gaps: list[str] = []

    summary_keywords = extract_keywords(request.document_summary)

    # 1) 도메인 일치
    if _normalize(case.domain) == _normalize(request.domain):
        reasons.append(f"두 문서 모두 '{case.domain}' 도메인에 속합니다.")
        common.append(f"현재 문서와 사례 모두 '{case.domain}' 도메인을 다룹니다.")

    # 2) 평가 항목 일치/불일치
    request_criteria_norm = {_normalize(c): c for c in request.evaluation_criteria}
    case_criteria_norm = {_normalize(c): c for c in case.evaluation_criteria}
    matched = [orig for key, orig in request_criteria_norm.items() if key in case_criteria_norm]
    case_only = [orig for key, orig in case_criteria_norm.items() if key not in request_criteria_norm]

    if matched:
        joined = ", ".join(matched[:3])
        reasons.append(f"동일한 평가 항목({joined})을 다룹니다.")
        for crit in matched[:_MAX_COMMON_POINTS]:
            common.append(f"평가 항목 '{crit}'이(가) 현재 문서와 사례 모두에서 확인됩니다.")

    # 탈락 사례는 "무엇이 부족해서 탈락했는지"를 추정할 근거가 없으므로, 평가 항목
    # 불일치를 different_points/gaps로 확장하지 않는다(섹션 17: 탈락 원인을 일반
    # 지식으로 만들어내지 않음).
    if case.case_type != SimilarCaseType.REJECTED_CASE:
        for crit in case_only[:_MAX_DIFFERENT_POINTS]:
            different.append(f"사례에는 평가 항목 '{crit}'에 해당하는 내용이 포함되어 있습니다.")
            gaps.append(_cannot_confirm(f"'{crit}'"))

    # 3) 문서 요약과 사례 청크 키워드 겹침
    matched_keywords: set[str] = set()
    case_only_keywords: set[str] = set()
    for chunk in case.supporting_chunks:
        chunk_keywords = extract_keywords(chunk.content)
        matched_keywords |= summary_keywords & chunk_keywords
        case_only_keywords |= chunk_keywords - summary_keywords

    for keyword in list(matched_keywords)[:_MAX_KEYWORDS_PER_CHUNK]:
        reasons.append(f"현재 문서 요약과 사례 내용 모두 '{keyword}' 관련 내용을 포함합니다.")
        common.append(f"'{keyword}' 관련 내용이 현재 문서 요약과 사례 모두에서 나타납니다.")

    if case.case_type != SimilarCaseType.REJECTED_CASE:
        for keyword in list(case_only_keywords)[:_MAX_KEYWORDS_PER_CHUNK]:
            different.append(f"사례에는 '{keyword}' 관련 내용이 포함되어 있습니다.")
            gaps.append(_cannot_confirm(f"'{keyword}'"))

    return ComparisonOutcome(
        similarity_reasons=reasons[:_MAX_REASONS],
        common_points=common[:_MAX_COMMON_POINTS],
        different_points=different[:_MAX_DIFFERENT_POINTS],
        current_document_gaps=gaps[:_MAX_GAPS],
        used_llm=False,
    )


def _build_llm_prompt(request: SimilarCaseSearchRequest, case: CaseAggregate) -> str:
    chunks_text = "\n".join(
        f"- (document_id={c.document_id}, chunk_id={c.chunk_id}) {c.content}" for c in case.supporting_chunks
    )
    criteria_text = ", ".join(request.evaluation_criteria)
    case_criteria_text = ", ".join(case.evaluation_criteria)
    return (
        "다음 정보만 사용해서 현재 문서와 사례를 비교하세요. 주어지지 않은 사실이나 수치를 "
        "만들어내지 마세요. 현재 문서에 없는 내용을 단정적으로 '없다'고 쓰지 말고 "
        "'확인하기 어렵습니다' 형태로 쓰세요.\n\n"
        f"[현재 문서 요약]\n{request.document_summary}\n\n"
        f"[현재 문서 평가 항목]\n{criteria_text}\n\n"
        f"[사례 제목] {case.title}\n"
        f"[사례 평가 항목]\n{case_criteria_text}\n"
        f"[사례 청크 원문]\n{chunks_text}\n\n"
        "다음 키를 가진 JSON 객체 하나만 출력하세요(설명 문장 없이 JSON만):\n"
        "{\"similarity_reasons\": [string], \"common_points\": [string], "
        "\"different_points\": [string], \"current_document_gaps\": [string]}"
    )


def _parse_llm_json(text: str) -> Optional[dict]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _compare_with_llm(
    request: SimilarCaseSearchRequest, case: CaseAggregate, llm_call: LLMCall
) -> Optional[ComparisonOutcome]:
    prompt = _build_llm_prompt(request, case)
    raw_response = llm_call(prompt)
    parsed = _parse_llm_json(raw_response)
    if parsed is None:
        return None

    required_keys = ("similarity_reasons", "common_points", "different_points", "current_document_gaps")
    values: dict[str, list[str]] = {}
    for key in required_keys:
        value = parsed.get(key)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            return None
        values[key] = value

    return ComparisonOutcome(
        similarity_reasons=values["similarity_reasons"][:_MAX_REASONS],
        common_points=values["common_points"][:_MAX_COMMON_POINTS],
        different_points=values["different_points"][:_MAX_DIFFERENT_POINTS],
        current_document_gaps=values["current_document_gaps"][:_MAX_GAPS],
        used_llm=True,
    )


__all__ = [
    "LLMCall",
    "SupportingChunk",
    "CaseAggregate",
    "ComparisonOutcome",
    "compare_case",
]
