# 작성자: 경이
# 목적: 위원(reviewer) 노드가 인용한 evidence_refs를 review_output.schema.json v2의
#       evidence[] 형식으로 변환한다(M4). 위원마다 별도 EvidencePool을 쓰고 evidence_id에
#       persona_id를 접두어로 붙여, 위원들이 병렬로(서로 모른 채, MTG-001) 실행되어도
#       충돌이나 조율 없이 각자 자기 근거를 등록할 수 있게 한다. 같은 근거를 여러 위원이
#       인용하면 evidence_id가 위원별로 따로 생기는 것을 허용한다(중복 제거는 하지 않음 —
#       병렬 독립 실행과 맞바꾼 의도적 단순화).
# import: 표준 라이브러리 typing만 사용.

from __future__ import annotations

from typing import Any

# reviewer_prompt.txt의 evidence_refs.source_type(rubric|submission|reference)을
# review_output.schema.json v2의 evidence.source_type(submission|notice|criteria|null)으로 옮긴다.
# 'reference'(외부 참고자료)는 v2 쪽에 대응 값이 없어 null로 둔다.
_SOURCE_TYPE_MAP = {"rubric": "criteria", "submission": "submission", "reference": None}


def _map_source_type(raw_source_type: str | None) -> str | None:
    if raw_source_type is None:
        return None
    return _SOURCE_TYPE_MAP.get(raw_source_type)


class EvidencePool:
    """한 위원이 인용한 근거를 v2 evidence[] 항목으로 등록하고 evidence_id를 발급한다."""

    def __init__(self, persona_id: str, retrieved_evidence: list[dict] | None = None):
        self._persona_id = persona_id
        self._pool_by_chunk = {
            item["chunk_id"]: item for item in (retrieved_evidence or []) if item.get("chunk_id")
        }
        self._by_key: dict[str, str] = {}
        self._linked_by_key: dict[tuple, str] = {}
        self._evidence: dict[str, dict] = {}

    def register(self, ref: dict[str, Any]) -> str:
        """위원이 인용한 evidence_ref 하나를 등록하고 evidence_id를 반환한다.

        같은 chunk_id(또는 chunk_id가 없으면 인용문 일부)를 이 위원이 두 번 인용하면
        동일한 evidence_id를 재사용한다.
        """
        chunk_id = ref.get("chunk_id")
        key = chunk_id or f"quote:{(ref.get('quote') or '')[:30]}"
        if key in self._by_key:
            return self._by_key[key]

        base = self._pool_by_chunk.get(chunk_id, {}) if chunk_id else {}
        evidence_id = f"EV-{self._persona_id}-{len(self._evidence) + 1:03d}"
        page = ref.get("page") or base.get("page")
        self._evidence[evidence_id] = {
            "evidence_id": evidence_id,
            "chunk_id": chunk_id or "unknown",
            "document_name": base.get("document_name") or ref.get("source_id") or "unknown",
            "source_type": _map_source_type(ref.get("source_type")),
            "page": page,
            "section": base.get("section"),
            "text": base.get("text") or ref.get("quote") or "",
            "quote": ref.get("quote"),
            "relevance": ref.get("relevance"),
            "score": base.get("score", 0.5),
        }
        self._by_key[key] = evidence_id
        return evidence_id

    def register_linked(self, ref: dict[str, Any]) -> str:
        """RAG-004 linked evidence(MeetingLinkedEvidenceRef) 1건을 등록하고 evidence_id를
        반환한다(A안). (document_id, chunk_id)로 역조회해, 같은 근거를 이 위원이 여러 번
        인용하면 동일 evidence_id를 재사용한다. linked ref엔 text가 없어(quote만 있음)
        retrieved_evidence 풀에서 chunk_id로 원문을 보강한다."""
        chunk_id = ref.get("chunk_id")
        key = (ref.get("document_id"), chunk_id)
        if key in self._linked_by_key:
            return self._linked_by_key[key]

        base = self._pool_by_chunk.get(chunk_id, {}) if chunk_id else {}
        evidence_id = f"EV-{self._persona_id}-{len(self._evidence) + 1:03d}"
        score = ref.get("final_score")
        if score is None:
            score = base.get("score", 0.5)
        score = min(max(float(score), 0.0), 1.0)
        self._evidence[evidence_id] = {
            "evidence_id": evidence_id,
            "chunk_id": chunk_id or "unknown",
            "document_name": ref.get("document_name") or base.get("document_name") or ref.get("document_id") or "unknown",
            "source_type": None,
            "page": ref.get("page") if ref.get("page") is not None else base.get("page"),
            "section": ref.get("section") or base.get("section"),
            "text": base.get("text") or ref.get("quote") or "",
            "quote": ref.get("quote"),
            "relevance": None,
            "score": score,
        }
        self._linked_by_key[key] = evidence_id
        return evidence_id

    def as_list(self) -> list[dict]:
        return list(self._evidence.values())
