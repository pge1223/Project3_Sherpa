"""
Input Adapters: DocumentExtractionResult / CleanedWebContent -> UnifiedBlock
==============================================================================
ai.rag.parsers / ai.rag.loaders / ai.rag.preprocessing는 전혀 수정하지 않고,
그 결과 스키마를 읽기만 해서 청킹 전용 내부 블록 구조로 변환한다.
"""

from dataclasses import dataclass
from typing import Optional

from ai.rag.parsers.schemas import DocumentExtractionResult, BlockType, FileType
from ai.rag.preprocessing.schemas import CleanedWebContent
from ai.rag.loaders.schemas import WebBlockType
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

    return unified


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
