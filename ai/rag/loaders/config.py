"""
URL Loader Configuration
=========================
URL 기반 문서 수집 시 적용되는 처리 제한값
"""

# 첨부파일 처리 제한
MAX_ATTACHMENTS: int = 10                       # 실제로 다운로드/파싱을 시도하는 첨부파일 최대 개수
MAX_ATTACHMENT_CANDIDATES: int = 30             # HTML에서 첨부 "후보"로 탐색하는 링크 최대 개수 (다운로드 전 단계)

# 크기 제한
MAX_ATTACHMENT_SIZE_BYTES: int = 20 * 1024 * 1024   # 개별 첨부파일 최대 20MB
MAX_HTML_PAGE_SIZE_BYTES: int = 20 * 1024 * 1024    # HTML 본문 자체의 최대 다운로드 크기
MAX_TOTAL_DOWNLOAD_SIZE_BYTES: int = 50 * 1024 * 1024  # URL 1건 처리 시 전체 다운로드 누적 최대 50MB

# 네트워크 제한
MAX_REDIRECTS: int = 5
CONNECT_TIMEOUT_SECONDS: float = 5.0
READ_TIMEOUT_SECONDS: float = 15.0

# 스트리밍 다운로드 청크 크기
DOWNLOAD_CHUNK_SIZE_BYTES: int = 64 * 1024

# HTML 페이지 재귀 탐색 여부 (요구사항: 다른 HTML 페이지로는 재귀 탐색하지 않음)
FOLLOW_LINKED_HTML_PAGES: bool = False

# User-Agent (봇 차단 회피 목적이 아니라 서버 로그에서 식별 가능하도록 명시)
USER_AGENT: str = "AIReviewBoard-URLLoader/1.0 (+internal RAG collector)"

# 확장자 없는 다운로드 링크를 후보로 잡기 위한 URL 패턴 (경로/쿼리스트링에 대소문자 무관 포함 검사)
DOWNLOAD_LINK_PATTERNS: tuple[str, ...] = ("download", "file", "attach", "atch")

# 지원 확장자 / 미지원(경고 대상) 확장자
SUPPORTED_ATTACHMENT_EXTENSIONS: tuple[str, ...] = ("pdf", "docx", "pptx")
UNSUPPORTED_ATTACHMENT_EXTENSIONS: tuple[str, ...] = ("hwp", "hwpx")


def get_loader_config() -> dict:
    """현재 로더 설정값 스냅샷 반환 (디버깅/로깅용)"""
    return {
        "max_attachments": MAX_ATTACHMENTS,
        "max_attachment_candidates": MAX_ATTACHMENT_CANDIDATES,
        "max_attachment_size_bytes": MAX_ATTACHMENT_SIZE_BYTES,
        "max_total_download_size_bytes": MAX_TOTAL_DOWNLOAD_SIZE_BYTES,
        "max_redirects": MAX_REDIRECTS,
        "connect_timeout_seconds": CONNECT_TIMEOUT_SECONDS,
        "read_timeout_seconds": READ_TIMEOUT_SECONDS,
        "follow_linked_html_pages": FOLLOW_LINKED_HTML_PAGES,
    }
