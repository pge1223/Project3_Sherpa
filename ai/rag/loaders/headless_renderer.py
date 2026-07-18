"""
Headless Browser Renderer (Playwright fallback)
================================================
requests 기반 정적 fetch(url_loader.py의 기본 경로)로는 JS/AJAX가 나중에 채워 넣는
콘텐츠를 볼 수 없다 — HTML 자체를 그대로 읽기만 하고 <script>를 실행하지 않기 때문이다.
실측(sotong.go.kr, 2026-07-18): 실제 진행 중인 공모전 공고 상세 페이지가 초기 HTML엔
"로딩 중..."만 있고, 본문(평가기준·마감일 등)은 페이지가 뜬 뒤 별도 AJAX 요청으로
채워지는 구조였다 — 정적 fetch로는 이 내용을 영원히 못 가져온다.

이 모듈은 그 경우에만(html_parser.is_js_rendered_suspected가 True일 때) url_loader.py가
호출하는 폴백이다 — 항상 타지 않는다(브라우저 프로세스 기동 자체가 정적 fetch보다
훨씬 비쌈, 수백ms~수초).

안전장치:
- 타임아웃: 예전에 색인 단계에서 타임아웃 없는 호출이 5분 넘게 멈춘 hang 버그를 실제로
  겪었다(같은 세션 회의록) — 같은 사고가 여기서 재발하지 않도록 페이지 이동(goto)과 전체
  페이지 컨텍스트 모두에 명시적 타임아웃을 건다. 실패(타임아웃/브라우저 미설치/크래시)는
  HeadlessRenderError로 통일해서 던지고, 호출부(url_loader.py)가 잡아 정적 fetch 결과로
  안전하게 폴백한다 — 요청 자체를 실패시키지 않는다.
- SSRF: file_downloader.open_stream()은 리다이렉트 매 hop마다 validate_url_or_raise()로
  사설/루프백 IP를 막는데, Playwright의 page.goto()는 리다이렉트를 브라우저가 내부적으로
  알아서 따라가 버려서 그 검증을 우회한다 — 페이지 자체 탐색(문서 요청)에 한해 같은
  validate_url_or_raise()를 라우트 훅으로 강제한다(이미지/스크립트 등 하위 리소스까지
  전부 검사하면 페이지당 요청 수만큼 DNS 조회가 늘어나 느려지므로 범위를 문서 탐색으로
  좁혔다).
"""

from __future__ import annotations

import logging

from ai.rag.loaders.config import (
    HEADLESS_NAVIGATION_TIMEOUT_SECONDS,
    HEADLESS_WAIT_AFTER_LOAD_SECONDS,
)
from ai.rag.loaders.exceptions import BlockedUrlError, HeadlessRenderError, InvalidUrlError
from ai.rag.loaders.file_downloader import validate_url_or_raise

logger = logging.getLogger(__name__)


def _block_unsafe_navigation(route) -> None:
    """문서 탐색(최초 진입 + 리다이렉트 + 프레임 이동) 요청에만 SSRF 검증을 강제한다."""
    request = route.request
    if request.resource_type == "document":
        try:
            validate_url_or_raise(request.url)
        except (InvalidUrlError, BlockedUrlError) as exc:
            logger.warning("헤드리스 브라우저 탐색 차단(SSRF 방지): %s (%s)", request.url, exc)
            route.abort()
            return
    route.continue_()


def render_with_headless_browser(url: str) -> str:
    """URL을 실제 Chromium으로 렌더링해서(AJAX 완료까지 기다린 뒤) 최종 HTML을 반환한다.

    Raises:
        HeadlessRenderError: 브라우저가 설치되지 않았거나, 타임아웃, 그 외 렌더링 실패
    """
    try:
        from playwright.sync_api import sync_playwright, Error as PlaywrightError
    except ImportError as exc:
        raise HeadlessRenderError(
            "playwright가 설치되어 있지 않습니다. 'pip install playwright && "
            "playwright install chromium'으로 설치해주세요."
        ) from exc

    navigation_timeout_ms = HEADLESS_NAVIGATION_TIMEOUT_SECONDS * 1000
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page()
                page.set_default_timeout(navigation_timeout_ms)
                page.route("**/*", _block_unsafe_navigation)
                # networkidle: 네트워크 요청이 500ms 이상 없을 때까지 대기 — AJAX 응답을
                # 기다리는 게 목적이므로 domcontentloaded(초기 HTML만)보다 이걸 쓴다.
                page.goto(url, wait_until="networkidle", timeout=navigation_timeout_ms)
                # networkidle 판정 이후에도 JS가 DOM을 마저 그리는 경우가 있어(리액트
                # 렌더 사이클 등) 약간의 여유시간을 더 둔다.
                page.wait_for_timeout(HEADLESS_WAIT_AFTER_LOAD_SECONDS * 1000)
                html = page.content()
            finally:
                browser.close()
    except PlaywrightError as exc:
        raise HeadlessRenderError(f"헤드리스 브라우저 렌더링에 실패했습니다: {url} ({exc})") from exc

    if not html:
        raise HeadlessRenderError(f"헤드리스 브라우저가 빈 HTML을 반환했습니다: {url}")

    return html
