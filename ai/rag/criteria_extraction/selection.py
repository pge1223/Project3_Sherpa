"""
Candidate Chunk Selection
============================
평가기준 후보 구간 탐지. LLM에 문서 전체를 보내지 않고, 평가기준/배점표로 보이는
청크만 추려 프롬프트에 넣는다 — 비용을 줄이고, 무관한 구간에서 평가기준을 지어낼
여지도 줄인다.
"""

from __future__ import annotations

import re

from ai.rag.chunking.schemas import Chunk, ContentKind

_SECTION_KEYWORDS = (
    "평가기준",
    "심사기준",
    "심사항목",
    "평가항목",
    "채점기준",
    "배점",
    "평가지표",
    "심사방법",
    "평가방법",
    "선정기준",
    "심사배점",
    "평가배점",
)

_KEYWORD_RE = re.compile("|".join(re.escape(keyword) for keyword in _SECTION_KEYWORDS))


def is_candidate_chunk(chunk: Chunk) -> bool:
    """청크가 평가기준 후보 구간인지 판단한다.

    표(content_kind=TABLE)는 배점표일 가능성이 높아 키워드 매칭 없이도 후보로
    포함한다. 그 외 본문/목차 청크는 section_title 또는 내용에 평가기준 관련
    키워드가 있을 때만 후보로 삼는다.
    """
    if chunk.content_kind == ContentKind.TABLE:
        return True
    haystack = f"{chunk.section_title or ''}\n{chunk.content}"
    return bool(_KEYWORD_RE.search(haystack))


def select_candidate_chunks(chunks: list[Chunk]) -> list[Chunk]:
    """indexable하지 않은 청크(TOC 등)는 제외하고, 후보 판정을 통과한 청크만
    문서 등장 순서(chunk_index) 그대로 반환한다."""
    candidates = [chunk for chunk in chunks if chunk.indexable and is_candidate_chunk(chunk)]
    return sorted(candidates, key=lambda chunk: chunk.chunk_index)
