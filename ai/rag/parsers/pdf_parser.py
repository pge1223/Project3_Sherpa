"""
PDF Parser using PyMuPDF
=======================
"""

import fitz  # PyMuPDF
from typing import Optional, Set

from ai.rag.parsers.base_parser import BaseParser
from ai.rag.parsers.base_ocr import BaseOCR, OCRResult
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

    def __init__(
        self,
        file_path: str,
        ocr_engine: Optional[BaseOCR] = None,
        enable_ocr: bool = True,
    ):
        """
        PDFParser 초기화

        Args:
            file_path: PDF 파일 경로
            ocr_engine: OCR 엔진 (기본값: None, lazy initialization)
            enable_ocr: OCR 활성화 여부 (기본값: True)
        """
        super().__init__(file_path)
        self._ocr_engine = ocr_engine
        self._enable_ocr = enable_ocr

    @property
    def ocr_engine(self) -> Optional[BaseOCR]:
        """OCR 엔진 지연 초기화 (lazy initialization)"""
        if self._ocr_engine is None and self._enable_ocr:
            self._ocr_engine = self._create_default_ocr_engine()
        return self._ocr_engine

    def _create_default_ocr_engine(self) -> Optional[BaseOCR]:
        """
        기본 OCR 엔진 생성 시도

        EasyOCR을 우선 시도하고, 사용 불가능하면 None 반환
        """
        try:
            from ai.rag.parsers.easyocr_engine import EasyOCR
            ocr = EasyOCR(languages=["ko", "en"], gpu=True)
            if ocr.is_available():
                return ocr
            return None
        except ImportError:
            return None

    def is_ocr_available(self) -> bool:
        """OCR 엔진 사용 가능 여부"""
        return self.ocr_engine is not None and self.ocr_engine.is_available()

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

    def _extract_image_with_ocr(
        self,
        page: fitz.Page,
        img: tuple,
        page_num: int,
        document_id: str,
        global_order: int,
    ) -> tuple[DocumentBlock, int]:
        """
        페이지에서 이미지를 추출하고 OCR 수행

        Args:
            page: PyMuPDF 페이지 객체
            img: 이미지 정보 튜플
            page_num: 페이지 번호 (1부터 시작)
            document_id: 문서 ID
            global_order: 글로벌 순서

        Returns:
            tuple[DocumentBlock, int]: OCR 결과 블록 및 업데이트된 global_order
        """
        ocr_result: OCRResult | None = None
        ocr_performed = False
        ocr_confidence = 0.0

        # 이미지에서 텍스트 추출 시도
        try:
            xref = img[0]
            base_image = page.parent.extract_image(xref)
            image_bytes = base_image["image"]

            if self.is_ocr_available():
                ocr_result = self.ocr_engine.extract_text_from_bytes(image_bytes)
                ocr_performed = True
                ocr_confidence = ocr_result.confidence
        except Exception as e:
            # OCR 실패 시 조용히 진행
            pass

        # OCR 결과 또는 폴백 텍스트 설정
        if ocr_performed and ocr_result and ocr_result.text.strip():
            content = ocr_result.text.strip()
            metadata = {
                "xref": img[0],
                "ocr_engine": self.ocr_engine.name if self.ocr_engine else None,
                "ocr_confidence": ocr_confidence,
                "ocr_performed": True,
            }
        else:
            content = "[이미지 - 텍스트 없음]"
            metadata = {
                "xref": img[0],
                "ocr_performed": ocr_performed,
            }

        block_obj = DocumentBlock(
            block_id=self.generate_block_id(
                document_id,
                LocationType.PAGE,
                page_num,
                global_order,
            ),
            block_type=BlockType.IMAGE,
            content=content,
            location_type=LocationType.PAGE,
            location_number=page_num,
            order=global_order,
            metadata=metadata,
        )

        return block_obj, global_order + 1

    def parse(self) -> DocumentExtractionResult:
        """PDF 문서 파싱 (텍스트 + 이미지 OCR)"""
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
        ocr_images_count = 0
        ocr_failed_count = 0

        # 페이지 간 중복 OCR 방지: 이미 처리된 이미지 xref 추적
        processed_xrefs: Set[int] = set()

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

            # 이미지 블록 추출 및 OCR 수행
            # page.get_images()가 반환하는 이미지 중 실제 페이지에 표시되는 것만 필터링
            page_images = page.get_images(full=True)

            for img_index, img in enumerate(page_images):
                xref = img[0]

                # 이미 전체 문서에서 처리된 이미지인지 확인
                if xref in processed_xrefs:
                    continue

                # 해당 이미지가 현재 페이지에 실제 표시되는지 확인
                try:
                    rects = page.get_image_rects(xref)
                    if not rects:
                        # rect가 없으면 현재 페이지에 표시되지 않는 이미지
                        continue
                except Exception:
                    # get_image_rects 실패 시 안전하게 건너뛰기
                    continue

                # 처리 대상으로 표시
                processed_xrefs.add(xref)

                block_obj, global_order = self._extract_image_with_ocr(
                    page=page,
                    img=img,
                    page_num=page_num + 1,
                    document_id=document_id,
                    global_order=global_order,
                )
                blocks.append(block_obj)
                ocr_images_count += 1
                if block_obj.metadata.get("ocr_performed") and not block_obj.content.startswith("[이미지"):
                    pass  # OCR 성공
                elif block_obj.metadata.get("ocr_performed"):
                    ocr_failed_count += 1

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

        # OCR 관련 경고 추가
        if self._enable_ocr and not self.is_ocr_available():
            warnings.append(
                "EasyOCR이 설치되어 있지 않습니다. 이미지 OCR을 건너뜁니다. "
                "pip install easyocr으로 설치해주세요."
            )

        # OCR 성공 후 텍스트가 비어 있는 경우 경고
        if ocr_images_count > 0 and ocr_failed_count == ocr_images_count:
            warnings.append(
                f"모든 이미지 OCR이 실패했습니다. 이미지가 스캔된 텍스트가 아니거나 "
                f"OCR 모델이 해당 언어를 지원하지 않을 수 있습니다."
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
