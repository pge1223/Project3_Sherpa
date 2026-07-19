"""
Notice Criteria Extraction Service
======================================
공고문 청킹 결과(ai.rag.chunking.chunk_document()의 출력)에서 평가기준을 추출해
contracts/mocks/notice_criteria_*.json과 동일한 구조(NoticeCriteriaResult)로 반환한다.

LLM 호출은 ai/meeting/graph/llm.py와 동일한 Callable[[str], str] 인터페이스로
생성자 주입한다(ai.meeting을 import하지 않고 동일한 관례만 따른다) — 실제 연동은
이 시그니처를 구현하는 함수를 넣기만 하면 되고, 테스트에서는 고정 응답을 돌려주는
stub 함수를 쓴다.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from ai.rag.chunking.schemas import Chunk
from ai.rag.criteria_extraction.normalize import normalize_criterion_key, normalize_weight
from ai.rag.criteria_extraction.prompt import build_extraction_prompt
from ai.rag.criteria_extraction.schemas import (
    EXPECTED_DOCUMENT_ROLE,
    CriteriaExtractionRequest,
    Criterion,
    ExtractionStatus,
    NoticeCriteriaMeta,
    NoticeCriteriaResult,
)
from ai.rag.criteria_extraction.selection import select_candidate_chunks

logger = logging.getLogger(__name__)

LLMCall = Callable[[str], str]


class CriteriaExtractionError(RuntimeError):
    """LLM 응답을 criteria 목록으로 해석할 수 없을 때 발생한다(JSON 파싱 실패 등)."""


def _parse_json_response(text: str) -> dict[str, Any]:
    """LLM 응답 문자열에서 JSON 객체를 파싱한다.

    프롬프트는 마크다운 코드블록 없이 JSON만 반환하라고 지시하지만, 실제 LLM은
    종종 ```json ... ``` 로 감싸 응답하므로 방어적으로 벗겨낸다
    (ai/meeting/graph/llm.py의 parse_json_response와 동일한 방어 로직).
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    return json.loads(cleaned)


class CriteriaExtractionService:
    def __init__(self, llm_call: LLMCall):
        self._llm_call = llm_call

    def extract(self, request: CriteriaExtractionRequest) -> NoticeCriteriaResult:
        if not request.has_expected_role:
            return self._empty_result(
                request,
                status=ExtractionStatus.SKIPPED_WRONG_ROLE,
                warnings=[
                    f"document_role={request.document_role!r}은(는) "
                    f"{EXPECTED_DOCUMENT_ROLE!r}가 아니어서 추출을 건너뛰었습니다."
                ],
            )

        candidates = select_candidate_chunks(request.chunks)
        if not candidates:
            return self._empty_result(
                request,
                status=ExtractionStatus.NO_CANDIDATE_SECTION,
                warnings=["평가기준으로 보이는 구간(키워드/표)을 찾지 못했습니다."],
            )

        prompt = build_extraction_prompt(candidates)
        raw_response = self._llm_call(prompt)

        try:
            parsed = _parse_json_response(raw_response)
        except (json.JSONDecodeError, ValueError) as exc:
            raise CriteriaExtractionError(f"LLM 응답을 JSON으로 해석할 수 없습니다: {exc}") from exc

        raw_items = parsed.get("criteria", [])
        if not isinstance(raw_items, list):
            raise CriteriaExtractionError("LLM 응답의 'criteria'는 배열이어야 합니다")

        chunk_by_id = {chunk.chunk_id: chunk for chunk in candidates}
        criteria, warnings = self._build_criteria(raw_items, chunk_by_id)

        status = ExtractionStatus.EXTRACTED if criteria else ExtractionStatus.NOT_FOUND
        return NoticeCriteriaResult(
            meta=NoticeCriteriaMeta(
                extraction_status=status,
                candidate_chunk_count=len(candidates),
                warnings=warnings,
            ),
            domain=request.domain,
            notice_document_id=request.notice_document_id,
            notice_title=request.notice_title,
            criteria=criteria,
        )

    def _build_criteria(
        self, raw_items: list[Any], chunk_by_id: dict[str, Chunk]
    ) -> tuple[list[Criterion], list[str]]:
        warnings: list[str] = []
        criteria: list[Criterion] = []
        seen_ids: set[str] = set()
        seen_name_keys: set[str] = set()

        for index, raw_item in enumerate(raw_items):
            if not isinstance(raw_item, dict):
                warnings.append(f"criteria[{index}]가 객체가 아니어서 건너뛰었습니다.")
                continue

            criterion_id = str(raw_item.get("criterion_id") or "").strip()
            name = str(raw_item.get("name") or "").strip()
            description = str(raw_item.get("description") or "").strip()
            source_text = str(raw_item.get("source_text") or "").strip()

            if not criterion_id or not name or not source_text:
                warnings.append(
                    f"criteria[{index}](criterion_id={criterion_id!r})에 필수 필드가 없어 "
                    "건너뛰었습니다."
                )
                continue

            if criterion_id in seen_ids:
                warnings.append(f"criterion_id={criterion_id!r} 중복이라 이후 항목을 건너뛰었습니다.")
                continue

            name_key = normalize_criterion_key(name)
            if name_key in seen_name_keys:
                warnings.append(f"평가항목 이름={name!r} 중복이라 이후 항목을 건너뛰었습니다.")
                continue

            source_chunk_id = raw_item.get("source_chunk_id")
            source_chunk = chunk_by_id.get(source_chunk_id) if source_chunk_id else None
            if source_chunk_id and source_chunk is None:
                warnings.append(
                    f"criterion_id={criterion_id!r}의 source_chunk_id={source_chunk_id!r}가 "
                    "후보 청크 목록에 없어 페이지 정보를 채우지 못했습니다."
                )

            criteria.append(
                Criterion(
                    criterion_id=criterion_id,
                    name=name,
                    description=description,
                    weight=normalize_weight(raw_item.get("weight")),
                    source_text=source_text,
                    page=source_chunk.location_number if source_chunk else None,
                    source_chunk_id=source_chunk.chunk_id if source_chunk else None,
                )
            )
            seen_ids.add(criterion_id)
            seen_name_keys.add(name_key)

        return criteria, warnings

    @staticmethod
    def _empty_result(
        request: CriteriaExtractionRequest,
        *,
        status: ExtractionStatus,
        warnings: list[str],
    ) -> NoticeCriteriaResult:
        return NoticeCriteriaResult(
            meta=NoticeCriteriaMeta(
                extraction_status=status,
                candidate_chunk_count=0,
                warnings=warnings,
            ),
            domain=request.domain,
            notice_document_id=request.notice_document_id,
            notice_title=request.notice_title,
            criteria=[],
        )
