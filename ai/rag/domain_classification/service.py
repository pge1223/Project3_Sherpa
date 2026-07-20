"""
Domain Classification Service (DOM-001)
===========================================
공고문/평가 대상 문서의 청킹 결과 또는 정제된 텍스트를 받아 competition /
government_support / startup 중 하나로 분류하고, 확신이 낮으면 unknown으로
남긴다.

LLM 호출은 ai/meeting/graph/llm.py, ai/rag/criteria_extraction/service.py와 동일한
Callable[[str], str] 인터페이스로 생성자 주입한다(ai.meeting은 import하지 않고
관례만 따른다) — 테스트에서는 고정 응답을 돌려주는 stub 함수를 쓴다.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Optional

from ai.rag.chunking.schemas import Chunk
from ai.rag.domain_classification.config import DomainClassificationConfig
from ai.rag.domain_classification.normalize import normalize_confidence, normalize_domain_label
from ai.rag.domain_classification.prompt import build_classification_prompt
from ai.rag.domain_classification.schemas import (
    DomainClassificationRequest,
    DomainClassificationResult,
    DomainLabel,
)

logger = logging.getLogger(__name__)

LLMCall = Callable[[str], str]

_EMPTY_DOCUMENT_REASONING = "분류할 문서 내용이 없습니다."
_UNPARSABLE_CONFIDENCE_REASONING_SUFFIX = " (confidence를 해석할 수 없어 보수적으로 UNKNOWN 처리)"
_UNKNOWN_LABEL_REASONING_SUFFIX = " (알 수 없는 라벨이라 보수적으로 UNKNOWN 처리)"
_LOW_CONFIDENCE_REASONING_SUFFIX_TEMPLATE = " (confidence({confidence:.2f}) < 임계값({threshold:.2f})이라 UNKNOWN 처리)"


class DomainClassificationError(RuntimeError):
    """LLM 응답을 분류 결과로 해석할 수 없을 때 발생한다(JSON 파싱 실패 등)."""


def _parse_json_response(text: str) -> dict[str, Any]:
    """LLM 응답 문자열에서 JSON 객체를 파싱한다. 마크다운 코드블록으로 감싸 응답하는
    경우를 방어적으로 벗겨낸다(ai/rag/criteria_extraction/service.py와 동일한 로직)."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    return json.loads(cleaned)


def _build_document_text(request: DomainClassificationRequest, max_chars: int) -> str:
    """text가 주어지면 그대로 쓰고, 아니면 chunks를 chunk_index 순으로 이어붙여
    max_chars까지만 사용한다(문서 앞부분이 보통 성격을 가장 잘 드러낸다는 전제)."""
    if request.text is not None and request.text.strip():
        return request.text.strip()[:max_chars]

    sorted_chunks: list[Chunk] = sorted(request.chunks, key=lambda chunk: chunk.chunk_index)
    parts: list[str] = []
    total_len = 0
    for chunk in sorted_chunks:
        if not chunk.content.strip():
            continue
        remaining = max_chars - total_len
        if remaining <= 0:
            break
        piece = chunk.content.strip()[:remaining]
        parts.append(piece)
        total_len += len(piece)

    return "\n\n".join(parts).strip()


class DomainClassificationService:
    def __init__(self, llm_call: LLMCall, config: Optional[DomainClassificationConfig] = None):
        self._llm_call = llm_call
        self._config = config or DomainClassificationConfig()

    def classify(self, request: DomainClassificationRequest) -> DomainClassificationResult:
        document_text = _build_document_text(request, self._config.max_input_chars)
        if not document_text:
            return DomainClassificationResult(
                domain=DomainLabel.UNKNOWN,
                confidence=0.0,
                reasoning=_EMPTY_DOCUMENT_REASONING,
                warnings=["입력으로 받은 chunks/text에 공백이 아닌 내용이 없습니다."],
            )

        prompt = build_classification_prompt(document_text)
        raw_response = self._llm_call(prompt)

        try:
            parsed = _parse_json_response(raw_response)
        except (json.JSONDecodeError, ValueError) as exc:
            raise DomainClassificationError(f"LLM 응답을 JSON으로 해석할 수 없습니다: {exc}") from exc

        if not isinstance(parsed, dict):
            raise DomainClassificationError("LLM 응답은 JSON 객체여야 합니다")

        return self._build_result(parsed)

    def _build_result(self, parsed: dict[str, Any]) -> DomainClassificationResult:
        warnings: list[str] = []
        reasoning = str(parsed.get("reasoning") or "").strip() or "LLM이 근거를 제공하지 않았습니다."
        raw_label_value = parsed.get("domain")
        raw_label_str = raw_label_value if isinstance(raw_label_value, str) else None

        candidate_scores = self._normalize_scores(parsed.get("scores"), warnings)

        confidence = normalize_confidence(parsed.get("confidence"))
        if confidence is None:
            warnings.append(f"confidence 값({parsed.get('confidence')!r})을 숫자로 해석할 수 없습니다.")
            return DomainClassificationResult(
                domain=DomainLabel.UNKNOWN,
                confidence=0.0,
                reasoning=reasoning + _UNPARSABLE_CONFIDENCE_REASONING_SUFFIX,
                raw_domain_label=raw_label_str,
                candidate_scores=candidate_scores,
                warnings=warnings,
            )

        label = normalize_domain_label(raw_label_value)
        if label is None:
            warnings.append(f"domain 라벨({raw_label_value!r})을 알려진 라벨로 해석할 수 없습니다.")
            return DomainClassificationResult(
                domain=DomainLabel.UNKNOWN,
                confidence=confidence,
                reasoning=reasoning + _UNKNOWN_LABEL_REASONING_SUFFIX,
                raw_domain_label=raw_label_str,
                candidate_scores=candidate_scores,
                warnings=warnings,
            )

        if confidence < self._config.min_confidence:
            warnings.append(
                f"confidence({confidence:.2f})가 임계값({self._config.min_confidence:.2f}) 미만이라 "
                "UNKNOWN으로 처리했습니다."
            )
            return DomainClassificationResult(
                domain=DomainLabel.UNKNOWN,
                confidence=confidence,
                reasoning=reasoning
                + _LOW_CONFIDENCE_REASONING_SUFFIX_TEMPLATE.format(
                    confidence=confidence, threshold=self._config.min_confidence
                ),
                raw_domain_label=raw_label_str,
                candidate_scores=candidate_scores,
                warnings=warnings,
            )

        return DomainClassificationResult(
            domain=label,
            confidence=confidence,
            reasoning=reasoning,
            raw_domain_label=raw_label_str,
            candidate_scores=candidate_scores,
            warnings=warnings,
        )

    @staticmethod
    def _normalize_scores(raw_scores: object, warnings: list[str]) -> dict[str, float]:
        if raw_scores is None:
            return {}
        if not isinstance(raw_scores, dict):
            warnings.append("scores 필드가 객체가 아니어서 무시했습니다.")
            return {}

        normalized: dict[str, float] = {}
        for key, value in raw_scores.items():
            label = normalize_domain_label(key)
            if label is None:
                continue
            score = normalize_confidence(value)
            if score is None:
                continue
            normalized[label.value] = score
        return normalized
