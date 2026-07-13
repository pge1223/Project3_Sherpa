"""
PDF Parser using PyMuPDF
=======================
"""

import fitz  # PyMuPDF

from ai.rag.parsers.base_parser import BaseParser
from ai.rag.parsers.schemas import (
    FileType,
    LocationType,
    BlockType,
    DocumentBlock,
)
from ai.rag.parsers.exceptions import CorruptedDocumentError, EmptyDocumentError
from ai.rag.parsers.config import MIN_TEXT_LENGTH_PER_PAGE, SCAN_PAGE_RATIO_THRESHOLD


class PDFParser(BaseParser):
    """PyMuPDF 기반 PDF 파서"""

    def get_file_type(self) -> FileType:
        return FileType.PDF

    def get_page_count(self) -> int | None:
        try:
            doc = fitz.open(str(self.file_path))
            count = len(doc)
            doc.close()
            return count
        except Exception:
            return None

    def parse(self) -> DocumentExtractionResult:
        """PDF 문서 파싱"""
        file_size = self.file_path.stat().st_size
        warnings: list[str] = []
        blocks: list[DocumentBlock] = []
        scanned_pages: list[int] = []

        try:
            doc = fitz.open(str(self.file_path))
            page_count = len(doc)
        except Exception as e:
            raise CorruptedDocumentError(f"PDF 파일을 열 수 없습니다: {e}")

        document_id = self.generate_document_id(self.file_path)
        global_order = 0

        for page_num in range(page_count):
            page = doc[page_num]
            page_text = page.get_text("text").strip()

            # 페이지별 텍스트 길이 검사
            if len(page_text) < MIN_TEXT_LENGTH_PER_PAGE:
                scanned_pages.append(page_num + 1)

            # 텍스트 블록 추출
            text_dict = page.get_text("dict")

            for block in text_dict.get("blocks", []):
                if block.get("type") == 0:  # text block
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            text = span.get("text", "").strip()
                            if text:
                                block_obj = DocumentBlock(
                                    block_id=self.generate_block_id(
                                        document_id,
                                        LocationType.PAGE,
                                        page_num + 1,
                                        global_order,
                                    ),
                                    block_type=BlockType.TEXT,
                                    content=text,
                                    location_type=LocationType.PAGE,
                                    location_number=page_num + 1,
                                    order=global_order,
                                    metadata={
                                        "font_size": span.get("size", 0),
                                        "font_name": span.get("font", ""),
                                    },
                                )
                                blocks.append(block_obj)
                                global_order += 1

            # 이미지 블록 추가 (OCR 필요)
            for img_index, img in enumerate(page.get_images(full=True)):
                block_obj = DocumentBlock(
                    block_id=self.generate_block_id(
                        document_id,
                        LocationType.PAGE,
                        page_num + 1,
                        global_order,
                    ),
                    block_type=BlockType.IMAGE,
                    content="[이미지 - OCR 필요]",
                    location_type=LocationType.PAGE,
                    location_number=page_num + 1,
                    order=global_order,
                    metadata={
                        "xref": img[0],
                        "img_index": img_index,
                    },
                )
                blocks.append(block_obj)
                global_order += 1

        doc.close()

        # 스캔 PDF 판정
        is_scanned_pdf = False
        requires_ocr = False

        if scanned_pages:
            scan_ratio = len(scanned_pages) / page_count
            if scan_ratio >= SCAN_PAGE_RATIO_THRESHOLD:
                is_scanned_pdf = True
                requires_ocr = True
                warnings.append(
                    f"스캔 PDF로 판단됩니다. 페이지 {scanned_pages}이(가) 텍스트를 거의 포함하지 않습니다. "
                    f"OCR 처리가 필요할 수 있습니다."
                )
            else:
                # 일부 페이지만 스캔인 경우 경고만
                warnings.append(
                    f"일부 페이지(페이지 {scanned_pages})에서 텍스트 추출량이 적습니다."
                )

        if len(blocks) == 0:
            raise EmptyDocumentError(
                "PDF에서 텍스트를 추출할 수 없습니다. 스캔 문서이거나 손상된 파일일 수 있습니다."
            )

        return self.create_result(
            file_size=file_size,
            page_count=page_count,
            blocks=blocks,
            is_scanned_pdf=is_scanned_pdf,
            requires_ocr=requires_ocr,
            warnings=warnings,
        )
