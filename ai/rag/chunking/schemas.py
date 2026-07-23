"""
Pydantic Schemas for Document Chunking
========================================
ai.rag.parsers.schemas / ai.rag.loaders.schemas / ai.rag.preprocessing.schemas는
전혀 수정하지 않고, 이 모듈에서만 청킹 전용 스키마를 정의한다.
"""

import hashlib
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from ai.rag.chunking.config import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_SEPARATORS,
    CHUNKING_VERSION,
)


class SourceType(str, Enum):
    """청크 원본이 어떤 경로로 수집되었는지"""
    FILE_UPLOAD = "file_upload"        # 사용자가 직접 업로드한 PDF/DOCX/PPTX
    URL_ATTACHMENT = "url_attachment"  # URL 수집 중 다운로드된 첨부파일 (AttachmentExtractionResult.extraction)
    URL_WEBPAGE = "url_webpage"        # URL의 HTML 본문 (CleanedWebContent)
    # 용준/Claude(2026-07-22, 요청: 선택된 아이디어/사용자 답변을 target evidence로 색인) —
    # 파일도 URL도 아니고, 아이디어 회의 중 선택된 후보나 사용자 답변으로부터 프로그램이
    # 직접 조립한 텍스트다(ai/rag/orchestration/ideation_target_indexing_service.py). 기존
    # 3개 값 중 어느 것도 정확히 맞지 않아 새로 추가한다 — FILE_UPLOAD를 재사용하면 "실제
    # 파일을 업로드했다"는 의미가 왜곡된다.
    IDEATION_GENERATED = "ideation_generated"  # 아이디어 회의(선택된 후보/사용자 답변)에서 생성된 텍스트


class ChunkLocationType(str, Enum):
    """
    청크의 원문 위치 유형. parsers.LocationType을 재사용하지 않고 청킹 전용으로 신설한다
    (parsers.LocationType엔 웹 문서용 값이 없고, parsers/loaders에 대한 결합을 피하기 위함).
    """
    PAGE = "page"              # PDF
    SLIDE = "slide"            # PPTX
    DOCUMENT = "document"      # DOCX (페이지 개념 없음)
    WEB_SECTION = "web_section"  # HTML


class ContentKind(str, Enum):
    """청크 내용의 종류"""
    BODY = "body"
    TABLE = "table"
    TOC = "toc"


class ChunkSourceContext(BaseModel):
    """
    청킹 호출자가 조립해서 넘겨주는 컨텍스트.
    document_id를 파일명만으로 생성하지 않기 위한 명시적 입력 지점이며,
    나중에 MongoDB에 저장된 문서 ID를 그대로 흘려보낼 수 있다.
    """
    document_id: str = Field(..., description="호출자가 결정하는 문서 ID (예: 향후 MongoDB 문서 ID)")
    source_type: SourceType
    source_url: Optional[str] = Field(
        None, description="URL_ATTACHMENT면 첨부파일 URL, URL_WEBPAGE면 페이지 URL, FILE_UPLOAD면 보통 None"
    )
    source_page_url: Optional[str] = Field(
        None, description="URL_ATTACHMENT인 경우 첨부가 발견된 공고 페이지 URL (AttachmentExtractionResult.source_page_url)"
    )
    source_filename: Optional[str] = Field(None, description="파일 기반인 경우 파일명")
    document_title: Optional[str] = Field(
        None, description="웹페이지인 경우 호출자가 WebPageContent.title을 전달 (CleanedWebContent엔 title이 없음)"
    )
    parent_document_id: Optional[str] = Field(
        None, description="URL 첨부파일처럼 상위 문서(공고 페이지)가 별도로 존재하는 경우의 상위 문서 ID"
    )
    file_type: Optional[str] = Field(
        None, description="호출자가 아는 파일 형식. DocumentExtractionResult.file_type과 다르면 warning 처리됨"
    )


class ChunkingConfig(BaseModel):
    """청킹 처리 설정. chunk_id 생성에 쓰이는 fingerprint()를 포함한다."""
    chunk_size: int = DEFAULT_CHUNK_SIZE
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP
    separators: list[str] = Field(default_factory=lambda: list(DEFAULT_SEPARATORS))
    chunking_version: str = CHUNKING_VERSION

    @field_validator("chunk_size")
    @classmethod
    def _chunk_size_must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("chunk_size는 0보다 커야 합니다")
        return v

    @field_validator("chunk_overlap")
    @classmethod
    def _chunk_overlap_must_be_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("chunk_overlap은 0 이상이어야 합니다")
        return v

    @model_validator(mode="after")
    def _chunk_overlap_must_be_smaller_than_size(self) -> "ChunkingConfig":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap은 chunk_size보다 작아야 합니다")
        return self

    def fingerprint(self) -> str:
        """chunk_id 생성에 반영되는 설정 지문 (chunk_size/chunk_overlap/separators 기반)"""
        raw = f"{self.chunk_size}:{self.chunk_overlap}:{'|'.join(self.separators)}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


class Chunk(BaseModel):
    """청킹 최종 산출물. 하나의 chunk가 임베딩/색인의 기본 단위가 된다."""
    chunk_id: str
    document_id: str
    content: str
    chunk_index: int = Field(..., description="문서 전체 기준 0-based 전역 순번 (원문 등장 순서)")
    content_kind: ContentKind
    source_type: SourceType
    source_url: Optional[str] = None
    source_page_url: Optional[str] = None
    source_filename: Optional[str] = None
    file_type: Optional[str] = None
    location_type: ChunkLocationType = Field(..., description="필수 — 모든 청크는 위치 유형을 가져야 함")
    location_number: Optional[int] = Field(
        None, description="PDF 페이지/PPTX 슬라이드 번호. DOCX/HTML은 항상 None (가짜 값 생성 금지)"
    )
    section_title: Optional[str] = Field(None, description="직전 heading/TITLE 블록 텍스트. preamble이면 None")
    source_block_ids: list[str] = Field(
        default_factory=list, description="원본 DocumentBlock.block_id 목록 (WebContentBlock 기원이면 항상 빈 리스트)"
    )
    source_block_orders: list[int] = Field(default_factory=list, description="원본 블록들의 order 값 목록")
    char_count: int
    indexable: bool = True
    chunking_version: str = CHUNKING_VERSION
    metadata: dict = Field(default_factory=dict)


class ChunkingResult(BaseModel):
    """chunk_document()의 최종 반환 스키마"""
    document_id: str
    chunks: list[Chunk] = Field(default_factory=list)
    chunk_count: int
    warnings: list[str] = Field(default_factory=list)
    chunking_version: str = CHUNKING_VERSION
    config: ChunkingConfig
