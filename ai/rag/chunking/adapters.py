"""
Input Adapters: DocumentExtractionResult / CleanedWebContent -> UnifiedBlock
==============================================================================
ai.rag.parsers / ai.rag.loaders / ai.rag.preprocessing는 전혀 수정하지 않고,
그 결과 스키마를 읽기만 해서 청킹 전용 내부 블록 구조로 변환한다.
"""

import re
from dataclasses import dataclass, replace
from typing import Optional

from ai.rag.parsers.schemas import DocumentExtractionResult, BlockType, FileType
from ai.rag.preprocessing.schemas import CleanedWebContent
from ai.rag.loaders.schemas import WebBlockType
from ai.rag.chunking.config import (
    BULLET_MARKER_CHARS,
    DECORATIVE_SYMBOL_CHARS,
    PSEUDO_HEADING_MARKERS,
    SENTENCE_TERMINATOR_CHARS,
    looks_like_whole_line_heading,
)
from ai.rag.chunking.schemas import ChunkLocationType


@dataclass
class UnifiedBlock:
    """청킹 파이프라인 내부 전용 공통 블록 (DocumentBlock/WebContentBlock을 감싸지 않고 필요한 값만 복사)"""
    content: str
    kind: str  # "heading" | "paragraph" | "list" | "table"
    location_type: ChunkLocationType
    location_number: Optional[int]
    order: int
    source_block_id: Optional[str]
    metadata: dict


_FILE_TYPE_TO_LOCATION_TYPE: dict[FileType, ChunkLocationType] = {
    FileType.PDF: ChunkLocationType.PAGE,
    FileType.PPTX: ChunkLocationType.SLIDE,
    FileType.DOCX: ChunkLocationType.DOCUMENT,
}

# BlockType.IMAGE(OCR 텍스트)/SHAPE(PPTX 일반 도형)는 표/제목이 아니므로 본문(paragraph)으로 취급한다.
_PARSER_BLOCK_TYPE_TO_KIND: dict[BlockType, str] = {
    BlockType.TITLE: "heading",
    BlockType.TEXT: "paragraph",
    BlockType.LIST: "list",
    BlockType.TABLE: "table",
    BlockType.IMAGE: "paragraph",
    BlockType.SHAPE: "paragraph",
}

_WEB_BLOCK_TYPE_TO_KIND: dict[WebBlockType, str] = {
    WebBlockType.HEADING: "heading",
    WebBlockType.PARAGRAPH: "paragraph",
    WebBlockType.LIST: "list",
    WebBlockType.TABLE: "table",
}


def adapt_document_extraction_result(extraction: DocumentExtractionResult) -> list[UnifiedBlock]:
    """
    PDF/DOCX/PPTX 공통 어댑터. AttachmentExtractionResult.extraction도 동일한 타입이므로 그대로 재사용된다.
    location_number은 원본 값을 그대로 옮길 뿐, 없는 값(DOCX)을 새로 만들지 않는다.
    """
    location_type = _FILE_TYPE_TO_LOCATION_TYPE[extraction.file_type]
    unified: list[UnifiedBlock] = []

    for block in extraction.blocks:
        kind = _PARSER_BLOCK_TYPE_TO_KIND.get(block.block_type, "paragraph")
        metadata = dict(block.metadata)  # 원본 dict를 그대로 참조하지 않고 복사 (mutate 방지)
        metadata["original_block_type"] = block.block_type.value

        unified.append(UnifiedBlock(
            content=block.content,
            kind=kind,
            location_type=location_type,
            location_number=block.location_number,
            order=block.order,
            source_block_id=block.block_id,
            metadata=metadata,
        ))

    if extraction.file_type == FileType.PDF:
        # DOCX/PPTX는 파서가 이미 문단 단위로 블록을 만들어 이 정규화가 필요 없고(불필요하게
        # 적용하면 회귀 위험만 생김), PDF만 PyMuPDF가 시각적 줄/스팬 단위로 블록을 쪼갠다.
        unified = merge_wrapped_pdf_lines(unified)

    return unified


_DECORATIVE_SYMBOL_ONLY_RE = re.compile(rf"^[{re.escape(DECORATIVE_SYMBOL_CHARS)}]+$")
_BULLET_MARKER_ONLY_RE = re.compile(rf"^[{re.escape(BULLET_MARKER_CHARS)}]+$")
_SENTENCE_TERMINATOR_RE = re.compile(rf"[{re.escape(SENTENCE_TERMINATOR_CHARS)}]\s*$")
_NEW_ITEM_START_RE = re.compile(
    rf"^\s*(?:[-※{re.escape(PSEUDO_HEADING_MARKERS)}{re.escape(BULLET_MARKER_CHARS)}]|[①-⑩]|\d{{1,2}}[).])"
)


def _is_decorative_symbol_only(stripped_text: str) -> bool:
    return bool(stripped_text) and bool(_DECORATIVE_SYMBOL_ONLY_RE.match(stripped_text))


def _is_bullet_marker_only(stripped_text: str) -> bool:
    return bool(stripped_text) and bool(_BULLET_MARKER_ONLY_RE.match(stripped_text))


def _looks_like_sentence_end(text: str) -> bool:
    return bool(_SENTENCE_TERMINATOR_RE.search(text.rstrip()))


def _looks_like_new_item_start(stripped_text: str) -> bool:
    return bool(_NEW_ITEM_START_RE.match(stripped_text))


def merge_wrapped_pdf_lines(blocks: list[UnifiedBlock]) -> list[UnifiedBlock]:
    """
    PDF(특히 HWPX→PDF 변환)는 PyMuPDF가 시각적 줄/스팬 단위로 블록을 만들어, 한 문장이
    줄바꿈으로 감싸져도 각 줄이 독립된 paragraph 블록이 된다. 이후 청킹 단계에서 단위 내
    블록을 전부 "\n\n"으로 이어붙이면(chunker._build_unit_text_and_offsets) 문장 중간에
    불필요한 단락 경계가 생기고, 장식용 기호만 있는 줄(예: '‧')이 그대로 남는다.

    heading/list/table 블록, 제목처럼 보이는 whole-line(예: "1) 개요"), 페이지 경계는 절대
    건드리지 않는다 — 종결부호 없이 이어지는 일반 paragraph 블록만 공백으로 병합하고,
    순수 장식 기호(‧)만 있는 블록은 제거한다.

    '•'/'◦'/'∙'/'·' 같은 실제 글머리표는 삭제하지 않는다. 이 마커만 있는 블록(예: '•' 한 글자)을
    만나면 즉시 버리거나 이전 문장에 붙이지 않고, 다음 본문 블록과 결합해 "마커 텍스트" 형태의
    새 목록 항목으로 만든다 — 그래야 "이전 문장 + 글머리표" 오병합과 "글머리표만 있는 블록
    통째로 삭제"를 둘 다 피할 수 있다. 이렇게 만들어진 목록 항목은 이후 로직에서
    new-item-start로 인식되어, 뒤따르는 다른 글머리표 항목과 서로 합쳐지지 않는다.

    병합된 블록은 먼저 나온 블록의 order/source_block_id를 유지한다(따라잡힌 뒤쪽 블록들의
    개별 식별자는 청크 단위에서는 더 이상 필요하지 않음).
    """
    merged: list[UnifiedBlock] = []
    pending_bullet: Optional[UnifiedBlock] = None

    for block in blocks:
        if block.kind != "paragraph":
            if pending_bullet is not None:
                merged.append(pending_bullet)
                pending_bullet = None
            merged.append(block)
            continue

        stripped = block.content.strip()

        if _is_decorative_symbol_only(stripped):
            if pending_bullet is not None:
                merged.append(pending_bullet)
                pending_bullet = None
            continue  # 순수 장식 기호(‧)만 있는 줄은 제거 (앞뒤 문장은 서로 이어붙여짐)

        if pending_bullet is not None:
            same_location = (
                pending_bullet.location_type == block.location_type
                and pending_bullet.location_number == block.location_number
            )
            if same_location and not _is_bullet_marker_only(stripped) and not looks_like_whole_line_heading(stripped):
                merged.append(replace(pending_bullet, content=f"{pending_bullet.content} {stripped}"))
                pending_bullet = None
                continue
            # 다음 블록과 결합할 수 없으면(다른 위치/또 다른 마커/제목) 마커만 있던 블록을
            # 그대로 확정하고, 현재 block은 아래 일반 로직으로 새로 판단한다.
            merged.append(pending_bullet)
            pending_bullet = None

        if _is_bullet_marker_only(stripped):
            pending_bullet = replace(block, content=stripped)
            continue

        if merged:
            prev = merged[-1]
            can_merge = (
                prev.kind == "paragraph"
                and prev.location_type == block.location_type
                and prev.location_number == block.location_number
                and not _looks_like_sentence_end(prev.content)
                and not looks_like_whole_line_heading(prev.content)
                and not looks_like_whole_line_heading(stripped)
                and not _looks_like_new_item_start(stripped)
            )
            if can_merge:
                merged[-1] = replace(prev, content=f"{prev.content.rstrip()} {stripped}")
                continue

        merged.append(replace(block, content=stripped) if stripped != block.content else block)

    if pending_bullet is not None:
        merged.append(pending_bullet)

    return merged


def adapt_cleaned_web_content(cleaned: CleanedWebContent) -> list[UnifiedBlock]:
    """
    HTML 어댑터. location_number은 항상 None (order를 페이지 번호로 둔갑시키지 않음).
    WebContentBlock에는 block_id가 없으므로 source_block_id는 항상 None.
    """
    unified: list[UnifiedBlock] = []

    for block in cleaned.cleaned_blocks:
        kind = _WEB_BLOCK_TYPE_TO_KIND.get(block.block_type, "paragraph")
        metadata = dict(block.metadata)
        metadata["original_block_type"] = block.block_type.value

        unified.append(UnifiedBlock(
            content=block.content,
            kind=kind,
            location_type=ChunkLocationType.WEB_SECTION,
            location_number=None,
            order=block.order,
            source_block_id=None,
            metadata=metadata,
        ))

    return unified
