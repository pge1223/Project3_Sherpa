"""
URL-based Document Loading Module
==================================
공모전/정부지원사업 공고 URL에서 웹페이지 본문과 첨부파일(PDF/DOCX/PPTX)을 수집해
기존 ai.rag.parsers로 연결하는 모듈. ai.rag.parsers 코드는 수정하지 않는다.

사용 예시:
    from ai.rag.loaders import load_from_url

    result = load_from_url("https://example.go.kr/notice/123")
    if result.page_content:
        print(result.page_content.title)
    for attachment in result.attachments:
        print(attachment.file_name, attachment.extraction.block_count)
"""

from ai.rag.loaders.url_loader import load_from_url
from ai.rag.loaders.schemas import (
    FetchTargetType,
    AttachmentFileType,
    WebBlockType,
    WebContentBlock,
    WebPageContent,
    AttachmentLinkInfo,
    AttachmentExtractionResult,
    UnsupportedAttachment,
    FailedAttachment,
    UrlExtractionResult,
)
from ai.rag.loaders.exceptions import (
    LoaderError,
    InvalidUrlError,
    BlockedUrlError,
    UrlFetchError,
    TooManyRedirectsError,
    DownloadSizeLimitExceededError,
    ContentTypeMismatchError,
)

__all__ = [
    "load_from_url",
    # Schemas
    "FetchTargetType",
    "AttachmentFileType",
    "WebBlockType",
    "WebContentBlock",
    "WebPageContent",
    "AttachmentLinkInfo",
    "AttachmentExtractionResult",
    "UnsupportedAttachment",
    "FailedAttachment",
    "UrlExtractionResult",
    # Exceptions
    "LoaderError",
    "InvalidUrlError",
    "BlockedUrlError",
    "UrlFetchError",
    "TooManyRedirectsError",
    "DownloadSizeLimitExceededError",
    "ContentTypeMismatchError",
]
