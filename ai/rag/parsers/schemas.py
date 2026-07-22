"""
Pydantic Schemas for Document Parsing
=====================================
"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class FileType(str, Enum):
    """지원하는 파일 형식"""
    PDF = "pdf"
    DOCX = "docx"
    PPTX = "pptx"
    HWP = "hwp"
    HWPX = "hwpx"


class LocationType(str, Enum):
    """블록 위치 유형"""
    PAGE = "page"      # PDF 페이지
    SLIDE = "slide"   # PPTX 슬라이드
    DOCUMENT = "document"  # DOCX 문서 전체


class BlockType(str, Enum):
    """블록 유형"""
    TEXT = "text"       # 일반 텍스트
    TABLE = "table"     # 표
    TITLE = "title"    # 제목
    LIST = "list"      # 목록
    IMAGE = "image"    # 이미지 (OCR 필요)
    SHAPE = "shape"    # PPTX 도형


class DocumentBlock(BaseModel):
    """문서에서 추출된 단일 블록"""
    block_id: str = Field(..., description="고유 블록 ID (deterministic)")
    block_type: BlockType = Field(..., description="블록 유형")
    content: str = Field(..., description="추출된 텍스트")
    location_type: LocationType = Field(..., description="위치 유형")
    location_number: Optional[int] = Field(None, description="위치 번호 (페이지/슬라이드)")
    order: int = Field(..., description="문서 내 순서")
    metadata: dict = Field(default_factory=dict, description="추가 메타데이터")


class DocumentExtractionResult(BaseModel):
    """문서 추출 결과 (모든 포맷 공통)"""
    document_id: str = Field(..., description="문서 고유 ID (파일명 기반 hash)")
    file_name: str = Field(..., description="원본 파일명")
    file_type: FileType = Field(..., description="파일 형식")
    file_size: int = Field(..., description="파일 크기 (bytes)")
    page_count: Optional[int] = Field(None, description="총 페이지/슬라이드 수")
    block_count: int = Field(..., description="추출된 블록 수")
    blocks: list[DocumentBlock] = Field(default_factory=list, description="추출된 블록 목록")
    is_scanned_pdf: bool = Field(False, description="스캔 PDF 여부")
    requires_ocr: bool = Field(False, description="OCR 필요 여부")
    warnings: list[str] = Field(default_factory=list, description="경고 메시지 목록")
