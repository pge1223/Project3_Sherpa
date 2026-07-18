"""
Pydantic Schemas for URL-based Document Loading
================================================
ai.rag.parsers.schemas는 수정하지 않고, 여기서는 로더 전용 스키마만 정의한다.
첨부파일 파싱 결과는 기존 DocumentExtractionResult를 그대로 감싸서 재사용한다.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from ai.rag.parsers.schemas import DocumentExtractionResult


class FetchTargetType(str, Enum):
    """최초 URL이 HTML 페이지인지 직접 파일 링크인지"""
    HTML_PAGE = "html_page"
    DIRECT_FILE = "direct_file"


class AttachmentFileType(str, Enum):
    """첨부 링크에서 판별된(또는 아직 확정되지 않은) 파일 형식"""
    PDF = "pdf"
    DOCX = "docx"
    PPTX = "pptx"
    HWP = "hwp"
    HWPX = "hwpx"
    # 가은/Claude(2026-07-18): 공모전 공고가 포스터 이미지 한 장으로만 올라오는 경우가
    # 많아서(정부기관 사이트 실측 — sotong.go.kr) 추가. 다운로드 후 url_loader.py가
    # 1페이지 PDF로 감싸서 기존 PDFParser의 임베디드 이미지 OCR(EasyOCR, PR #6)을
    # 그대로 재사용한다 — 새 OCR 엔트리포인트를 만들지 않는다.
    JPEG = "jpeg"
    PNG = "png"
    UNKNOWN = "unknown"  # 확장자 없는 다운로드 링크 (다운로드 후 실제 형식 확인 필요)


class WebBlockType(str, Enum):
    """웹페이지 본문 블록 유형 (parsers.BlockType과 별개, 청킹 대비 구조)"""
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    TABLE = "table"


class WebContentBlock(BaseModel):
    """HTML 페이지 본문에서 추출된 단일 블록 (loaders 전용, parsers.DocumentBlock 미사용)"""
    content: str = Field(..., description="추출된 텍스트")
    block_type: WebBlockType = Field(..., description="블록 유형")
    order: int = Field(..., description="문서 내 순서")
    metadata: dict = Field(default_factory=dict, description="추가 메타데이터 (예: heading level, list_type)")


class WebPageContent(BaseModel):
    """정적 HTML 페이지 추출 결과"""
    url: str = Field(..., description="페이지 URL (리다이렉트 최종 도달 URL)")
    title: Optional[str] = Field(None, description="페이지 제목")
    blocks: list[WebContentBlock] = Field(default_factory=list, description="청킹 대비 구조화 블록")
    text: str = Field(..., description="블록을 합친 전체 텍스트 (미리보기/디버그용)")
    text_length: int = Field(..., description="전체 텍스트 길이")
    fetched_at: datetime = Field(..., description="수집 시각 (UTC)")
    encoding: str = Field(..., description="감지된 응답 인코딩")
    is_js_rendered_suspected: bool = Field(False, description="JS 렌더링 페이지 의심 여부 (경고용, 확정 오류 아님)")


class AttachmentLinkInfo(BaseModel):
    """HTML에서 탐색된 첨부파일 링크 후보 (attachment_finder.py 출력)"""
    url: str = Field(..., description="절대경로로 정규화된 첨부파일 URL")
    file_name: str = Field(..., description="URL/앵커 텍스트에서 유추한 파일명")
    extension: AttachmentFileType = Field(..., description="추정 파일 형식 (UNKNOWN이면 다운로드 후 확정)")
    anchor_text: Optional[str] = Field(None, description="<a> 태그 표시 텍스트")
    discovery_reasons: list[str] = Field(
        default_factory=list,
        description="후보로 탐색된 근거 (href_extension, anchor_text_extension, download_attribute, link_pattern 등)",
    )


class AttachmentExtractionResult(BaseModel):
    """다운로드 + 파싱까지 완료된 첨부파일 결과 (DocumentExtractionResult를 무수정으로 감쌈)"""
    attachment_url: str = Field(..., description="첨부파일 원본 URL")
    file_name: str = Field(..., description="최종 확정된 파일명")
    source_page_url: str = Field(..., description="첨부가 발견된 페이지 URL (직접 파일 링크면 origin_url과 동일)")
    extraction: DocumentExtractionResult = Field(..., description="기존 parsers.UnifiedParser 결과, 무변형")


class UnsupportedAttachment(BaseModel):
    """HWP/HWPX 등 현재 미지원 형식 (다운로드/파싱하지 않고 기록만 함)"""
    url: str
    file_name: str
    reason: str


class FailedAttachment(BaseModel):
    """다운로드 또는 파싱에 실패한 첨부파일 (내부 경로/traceback 등 민감 정보는 절대 포함하지 않음)"""
    url: str
    file_name: str
    error_code: str = Field(..., description="예: TIMEOUT, SIZE_LIMIT_EXCEEDED, CONTENT_TYPE_MISMATCH, CORRUPTED, BLOCKED_URL")
    message: str = Field(..., description="사용자에게 노출 가능한 요약 메시지")


class UrlExtractionResult(BaseModel):
    """url_loader.load_from_url()의 최종 반환 스키마"""
    origin_url: str = Field(..., description="사용자가 입력한 원본 URL")
    fetch_target_type: FetchTargetType
    fetched_at: datetime
    page_content: Optional[WebPageContent] = Field(None, description="DIRECT_FILE인 경우 None")
    attachments: list[AttachmentExtractionResult] = Field(default_factory=list)
    unsupported_attachments: list[UnsupportedAttachment] = Field(default_factory=list)
    failed_attachments: list[FailedAttachment] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
