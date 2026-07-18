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
SUPPORTED_ATTACHMENT_EXTENSIONS: tuple[str, ...] = ("pdf", "docx", "pptx", "jpg", "jpeg", "png")
UNSUPPORTED_ATTACHMENT_EXTENSIONS: tuple[str, ...] = ("hwp", "hwpx")

# 가은/Claude(2026-07-18): <img> 태그 탐색 시 로고/아이콘/공유버튼 같은 노이즈를 거르기
# 위한 최소 크기(px) — width/height 속성이 둘 다 있고 둘 다 이 값보다 작으면 후보에서
# 제외한다. 속성이 없거나(레이지로딩 등) 하나만 있으면 판단 근거 부족으로 통과시킨다
# (과탐보다 누락이 덜 위험하다고 보고 보수적으로 필터링).
MIN_IMAGE_ATTACHMENT_DIMENSION_PX: int = 120

# 가은/Claude(2026-07-18): 헤드리스 브라우저(Playwright) 렌더링 폴백 설정 — 정적
# requests fetch로 본문을 못 찾은(JS/AJAX 렌더링 의심) 페이지에만 쓴다. 브라우저 프로세스
# 기동 자체가 수백ms~수초라 비싸므로 fallback 전용, 항상 타지 않는다. 이전에 겪은 색인
# 단계 hang 버그(project3 회의록 2026-07-18)와 같은 사고가 새 기능에서 재발하지 않도록
# 반드시 타임아웃을 건다 — Playwright의 page.goto(timeout=...)이 실제 강제한다.
HEADLESS_NAVIGATION_TIMEOUT_SECONDS: float = 20.0
HEADLESS_WAIT_AFTER_LOAD_SECONDS: float = 1.5  # networkidle 이후 AJAX 렌더링 마무리 여유시간

# 가은/Claude(2026-07-18): 헤드리스 렌더링 "성공 여부" 재판정은 _detect_js_rendered_suspected
# 휴리스틱을 그대로 재사용하지 않는다 — 실측에서 메인 콘텐츠는 완전히 채워졌는데도 페이지
# 하단의 "관련 글 더보기" 같은 별개 위젯이 "로딩 중..."을 계속 띄우고 있어서
# is_js_rendered_suspected가 계속 True로 나오는(사실상 성공인데 실패로 오판) 케이스를
# 확인했다. 대신 렌더링된 본문 길이만으로 단순 판정한다.
MIN_RENDERED_TEXT_LENGTH_AFTER_HEADLESS: int = 300

# 가은/Claude(2026-07-18): 실측(sotong.go.kr) — 본문 텍스트 길이/script 태그 개수만 보는
# 기존 JS-렌더링 의심 휴리스틱이 "메뉴 등 주변 텍스트는 있지만 본문 영역만 AJAX로 채워지는"
# 페이지를 놓치는 걸 확인했다("로딩 중..."만 긁혀왔는데도 의심 안 함으로 판정). 이런
# 로딩 placeholder 문구가 본문에 있으면 그 자체로 의심 신호로 취급한다.
LOADING_PLACEHOLDER_PATTERNS: tuple[str, ...] = ("로딩 중", "loading...", "잠시만 기다려", "잠시 후 다시")


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
