# 작성자: 가은/Claude(2026-07-18)
# 목적: JS/AJAX 렌더링 페이지 폴백(ai.rag.loaders.headless_renderer, Playwright) 검증.
#       requests_mock으로는 흉내낼 수 없다 — Playwright는 실제 Chromium이 실제 TCP
#       연결로 요청을 보내기 때문이다. 대신 로컬 HTTP 서버를 띄워 AJAX 응답을 흉내낸다
#       (외부 네트워크는 전혀 타지 않음). 실측(sotong.go.kr, 같은 세션 회의록): 실제
#       진행 중인 공모전 공고 페이지가 정적 fetch로는 "로딩 중..."만 긁혀오는 걸
#       확인했고, 이 모듈로 실제 공고 내용(공모기간/참가대상/제출서류 등)까지 뽑히는
#       것도 실측 확인했다 — 여기 테스트는 그 핵심 동작을 로컬 fixture로 고정한다.
# import: 표준 라이브러리 http.server/threading/time, pytest; ai/rag/loaders 패키지.

import http.server
import threading
import time

import pytest

from ai.rag.loaders import file_downloader, url_loader
from ai.rag.loaders.exceptions import HeadlessRenderError
from ai.rag.loaders import headless_renderer

# 브라우저 프로세스 기동(수백ms~수초)이 필요해 느리다 — conftest.py에 이미 등록된
# slow 마커로 표시해서 기본 빠른 테스트 실행에서 제외할 수 있게 한다.
pytestmark = pytest.mark.slow


# 가은/Claude(2026-07-18): 콘텐츠 영역을 <p>로 감싼다 — html_parser._extract_blocks()가
# <div>는 레이아웃용으로 보고 의도적으로 무시하고 h1~h6/p/ul/ol/table만 본문으로 추출한다
# (실측 sotong.go.kr도 실제 콘텐츠는 <p>류로 렌더링됨). <div>로 만들었다가 AJAX
# 주입 자체는 성공해도 텍스트 추출 단계에서 계속 빈 문자열이 나와 처음에 이 테스트가
# 실패했었다 — 헤드리스 렌더링 문제가 아니라 테스트 fixture 문제였음.
_AJAX_PAGE_HTML = """
<html><head><title>테스트 공고</title></head>
<body>
<p>공모전 공고</p>
<p id="content">로딩 중...</p>
<script>
fetch('/api/content')
  .then(r => r.json())
  .then(data => { document.getElementById('content').innerText = data.text; });
</script>
</body></html>
"""

_NEVER_RESOLVES_HTML = """
<html><head><title>영원히 로딩</title></head>
<body>
<p id="content">로딩 중...</p>
<script>
fetch('/api/hang').then(r => r.json()).then(data => { document.getElementById('content').innerText = data.text; });
</script>
</body></html>
"""

# 가은/Claude(2026-07-18): url_loader.py는 렌더링 후 본문이 300자
# (MIN_RENDERED_TEXT_LENGTH_AFTER_HEADLESS) 미만이면 "충분히 채워지지 않았다" 경고를
# 별도로 남긴다 — 그 경고가 안 뜨는 것도 같이 검증하려면 실제 공고문 분량 정도로
# 충분히 길어야 한다.
_AJAX_CONTENT_TEXT = (
    "실제 공고 내용: 접수기간 2026-08-01~08-31, 배점 100점. "
    "본 공모전은 청년 창업가를 지원하기 위한 사업으로, 참가대상은 만 39세 이하 예비창업자 및 "
    "창업 3년 이내 기업입니다. 평가항목은 창의성(30점), 실현가능성(30점), 사업성(25점), "
    "완성도(15점)로 구성되며, 제출서류는 사업계획서와 재무제표를 포함합니다. "
    "문의처는 담당 부서 전화번호로 연락 바랍니다. 제출 방법은 온라인 접수시스템을 통한 "
    "전자 제출만 인정하며, 우편·방문 접수는 받지 않습니다. 심사는 서류심사와 발표심사 "
    "2단계로 진행되며, 서류심사 통과자에 한해 발표심사 일정을 개별 안내합니다."
)


class _AjaxTestHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002 - 테스트 출력 조용히
        pass

    def do_GET(self):
        if self.path == "/page":
            self._send_html(_AJAX_PAGE_HTML)
        elif self.path == "/api/content":
            self._send_html(f'{{"text": "{_AJAX_CONTENT_TEXT}"}}', content_type="application/json")
        elif self.path == "/never-resolves":
            self._send_html(_NEVER_RESOLVES_HTML)
        elif self.path == "/api/hang":
            # 절대 응답하지 않는다 — 헤드리스 렌더러가 타임아웃으로 스스로 끊어야 한다
            # (예전에 색인 단계에서 겪은 hang 버그와 같은 사고 재발 방지 회귀 테스트).
            time.sleep(3600)
        else:
            self.send_response(404)
            self.end_headers()

    def _send_html(self, body: str, content_type: str = "text/html; charset=utf-8"):
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


# 가은/Claude(2026-07-18): 일반 http.server.HTTPServer는 요청을 한 번에 하나씩만
# 처리한다(단일 스레드) — /api/hang(3600초 sleep, 타임아웃 회귀 테스트용)이 처리 중인
# 동안 서버 자체가 새 요청도 못 받고 server.shutdown()도 그 요청이 끝날 때까지 블로킹돼
# 테스트 스위트 전체가 멈추는 걸 실측했다. ThreadingHTTPServer로 요청마다 별도 스레드를
# 써서 hang 요청 하나가 서버 전체를 막지 못하게 한다.
@pytest.fixture
def local_server():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _AjaxTestHandler)
    server.daemon_threads = True
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.fixture(autouse=True)
def allow_loopback(monkeypatch):
    """url_loader.load_from_url()/headless_renderer 둘 다 SSRF 방지로 127.0.0.1을
    원래 차단한다 — 로컬 테스트 서버를 대상으로 할 때만 그 검증을 우회한다."""
    monkeypatch.setattr(file_downloader, "_is_blocked_ip", lambda ip_str: False)


def test_ajax_content_is_captured_after_headless_render(local_server):
    """핵심 시나리오: 정적 HTML엔 "로딩 중..."만 있고 실제 내용은 AJAX로 채워지는
    페이지 — url_loader.load_from_url()이 자동으로 헤드리스 렌더링까지 시도해서 실제
    콘텐츠를 가져와야 한다."""
    result = url_loader.load_from_url(f"{local_server}/page")

    assert result.page_content is not None
    assert _AJAX_CONTENT_TEXT in result.page_content.text
    # 성공적으로 폴백됐다는 신호 — "본문이 충분히 채워지지 않았습니다" 경고가 없어야 한다.
    assert not any("충분히 채워지지" in w for w in result.warnings)


def test_headless_render_direct_call_returns_ajax_injected_html(local_server):
    html = headless_renderer.render_with_headless_browser(f"{local_server}/page")
    assert _AJAX_CONTENT_TEXT in html


def test_never_resolving_page_times_out_not_hangs(local_server, monkeypatch):
    """무한 대기 대신 설정된 타임아웃 안에 HeadlessRenderError로 끝나야 한다 — 예전에
    색인 단계에서 실제로 겪은 hang 버그(5분+ 무응답)와 같은 사고가 새 기능에서 재발하지
    않는지 확인하는 회귀 테스트."""
    monkeypatch.setattr(headless_renderer, "HEADLESS_NAVIGATION_TIMEOUT_SECONDS", 2.0)

    started = time.time()
    with pytest.raises(HeadlessRenderError):
        headless_renderer.render_with_headless_browser(f"{local_server}/never-resolves")
    elapsed = time.time() - started

    assert elapsed < 15  # 설정한 타임아웃(2초)보다 넉넉히 여유를 둔 상한


def test_unreachable_host_raises_headless_render_error_not_hangs(monkeypatch):
    monkeypatch.setattr(headless_renderer, "HEADLESS_NAVIGATION_TIMEOUT_SECONDS", 2.0)
    started = time.time()
    with pytest.raises(HeadlessRenderError):
        headless_renderer.render_with_headless_browser("http://127.0.0.1:1/does-not-exist")
    assert time.time() - started < 15


def test_load_from_url_falls_back_gracefully_when_playwright_unavailable(local_server, monkeypatch):
    """헤드리스 렌더링 자체가 실패해도(브라우저 미설치 등) 전체 요청은 실패하지 않고
    정적 fetch 결과 + 경고로 안전하게 폴백해야 한다."""

    def _raise(url):
        raise HeadlessRenderError("모의 실패: 브라우저를 실행할 수 없습니다")

    monkeypatch.setattr(url_loader, "render_with_headless_browser", _raise)

    result = url_loader.load_from_url(f"{local_server}/page")

    assert result.page_content is not None
    assert "로딩 중" in result.page_content.text  # 정적 fetch 결과 그대로
    assert any("헤드리스 브라우저 재시도도 실패했습니다" in w for w in result.warnings)
