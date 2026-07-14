"""
Tests for URL-based Document Loading (ai.rag.loaders)
=======================================================
requests_mock으로 모든 HTTP 요청을 가로채며, 실제 외부 네트워크에는 접속하지 않는다.

호스트명 DNS 조회(socket.getaddrinfo)는 SSRF 방지 검증에 실제로 사용되므로,
테스트용 도메인(example.test 등)에 대해서만 결과를 가짜로 대체한다.
IP 리터럴(127.0.0.1 등)은 실제 getaddrinfo를 그대로 통과시켜 SSRF 차단 로직을 검증한다.
"""

import ipaddress
import socket

import pytest
import requests
import requests_mock

from ai.rag.loaders import url_loader
from ai.rag.loaders.exceptions import (
    InvalidUrlError,
    BlockedUrlError,
    UrlFetchError,
    TooManyRedirectsError,
    DownloadSizeLimitExceededError,
)
from ai.rag.loaders.schemas import FetchTargetType, AttachmentFileType
from ai.rag.loaders import attachment_finder, html_parser, file_downloader


# ---------------------------------------------------------------------------
# DNS 안전장치: 테스트 도메인은 실제 DNS 조회 없이 안전한 공인 IP로 처리
# ---------------------------------------------------------------------------

_FAKE_PUBLIC_IP = "93.184.216.34"


@pytest.fixture(autouse=True)
def fake_dns(monkeypatch):
    real_getaddrinfo = socket.getaddrinfo

    def _fake_getaddrinfo(host, *args, **kwargs):
        try:
            ipaddress.ip_address(host)
            return real_getaddrinfo(host, *args, **kwargs)  # IP 리터럴은 실제 검증 로직을 그대로 태움
        except ValueError:
            pass
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (_FAKE_PUBLIC_IP, 0))]

    monkeypatch.setattr(file_downloader.socket, "getaddrinfo", _fake_getaddrinfo)
    yield


@pytest.fixture
def mock_requests():
    with requests_mock.Mocker() as m:
        yield m


# ---------------------------------------------------------------------------
# url_loader: 직접 파일 링크
# ---------------------------------------------------------------------------

def test_direct_pdf_url_is_downloaded_and_parsed(mock_requests, sample_pdf):
    url = "http://example.test/notice/plan.pdf"
    mock_requests.get(url, content=sample_pdf.read_bytes(), headers={"Content-Type": "application/pdf"})

    result = url_loader.load_from_url(url)

    assert result.fetch_target_type == FetchTargetType.DIRECT_FILE
    assert result.page_content is None
    assert len(result.attachments) == 1
    assert result.attachments[0].extraction.file_type.value == "pdf"
    assert result.attachments[0].extraction.block_count > 0
    assert not result.failed_attachments


def test_direct_hwp_url_is_not_downloaded(mock_requests):
    url = "http://example.test/notice/plan.hwp"
    # 의도적으로 mock을 등록하지 않음: 만약 코드가 실제로 요청을 보내면 NoMockAddress로 테스트가 실패한다
    result = url_loader.load_from_url(url)

    assert result.fetch_target_type == FetchTargetType.DIRECT_FILE
    assert len(result.unsupported_attachments) == 1
    assert result.unsupported_attachments[0].url == url
    assert result.warnings
    assert mock_requests.call_count == 0


# ---------------------------------------------------------------------------
# url_loader: HTML 페이지 + 첨부파일
# ---------------------------------------------------------------------------

_SAMPLE_HTML = """
<html>
<head><title>2026년도 청년 창업 지원사업 공고</title></head>
<body>
  <h1>사업 개요</h1>
  <p>본 사업은 청년 창업가를 지원하기 위한 사업입니다.</p>
  <h2>제출 서류</h2>
  <ul>
    <li>사업계획서</li>
    <li>재무제표</li>
  </ul>
  <table>
    <tr><th>구분</th><th>내용</th></tr>
    <tr><td>지원 규모</td><td>1억원</td></tr>
  </table>
  <p>첨부파일을 확인하세요.</p>
  <a href="/files/plan.pdf">사업계획서 양식 다운로드</a>
  <a href="attachments/budget.docx">예산서 양식.docx</a>
  <a href="/files/legacy.hwp">기존 공고문.hwp</a>
  <a href="/cmm/fms/FileDown.do?atchFileId=abc123" download>붙임2 다운로드</a>
</body>
</html>
"""


def test_html_page_with_multiple_attachments(mock_requests, sample_pdf, sample_docx):
    page_url = "http://example.test/notice/123"
    mock_requests.get(page_url, text=_SAMPLE_HTML, headers={"Content-Type": "text/html; charset=utf-8"})
    mock_requests.get(
        "http://example.test/files/plan.pdf",
        content=sample_pdf.read_bytes(),
        headers={"Content-Type": "application/pdf"},
    )
    mock_requests.get(
        "http://example.test/notice/attachments/budget.docx",
        content=sample_docx.read_bytes(),
        headers={"Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    )
    mock_requests.get(
        "http://example.test/cmm/fms/FileDown.do?atchFileId=abc123",
        content=sample_pdf.read_bytes(),
        headers={
            "Content-Type": "application/octet-stream",
            "Content-Disposition": 'attachment; filename="붙임2.pdf"',
        },
    )
    # legacy.hwp는 등록하지 않음 -> 실제로 요청되면 NoMockAddress로 실패해야 함

    result = url_loader.load_from_url(page_url)

    assert result.fetch_target_type == FetchTargetType.HTML_PAGE
    assert result.page_content is not None
    assert result.page_content.title == "2026년도 청년 창업 지원사업 공고"
    assert any(b.block_type.value == "heading" for b in result.page_content.blocks)
    assert any(b.block_type.value == "list" for b in result.page_content.blocks)
    assert any(b.block_type.value == "table" for b in result.page_content.blocks)

    attachment_urls = {a.attachment_url for a in result.attachments}
    assert "http://example.test/files/plan.pdf" in attachment_urls
    assert "http://example.test/notice/attachments/budget.docx" in attachment_urls
    # 확장자 없는 다운로드 링크도 발견되어 실제 PDF로 확정 파싱됨
    assert "http://example.test/cmm/fms/FileDown.do?atchFileId=abc123" in attachment_urls

    assert len(result.unsupported_attachments) == 1
    assert result.unsupported_attachments[0].url.endswith("legacy.hwp")


def test_js_rendered_page_produces_warning_not_error(mock_requests):
    page_url = "http://example.test/notice/spa"
    scripts = "".join(f'<script src="/bundle{i}.js"></script>' for i in range(15))
    spa_html = f"<html><head><title>공고</title>{scripts}</head><body><div id='root'></div></body></html>"
    mock_requests.get(page_url, text=spa_html, headers={"Content-Type": "text/html"})

    result = url_loader.load_from_url(page_url)

    assert result.page_content.is_js_rendered_suspected is True
    assert any("JavaScript" in w for w in result.warnings)
    # 경고일 뿐 예외가 발생하지 않고 정상적으로 결과가 반환됨
    assert result.fetch_target_type == FetchTargetType.HTML_PAGE


# ---------------------------------------------------------------------------
# 크기 제한
# ---------------------------------------------------------------------------

def test_attachment_content_length_header_exceeds_limit(mock_requests, monkeypatch):
    monkeypatch.setattr(url_loader, "MAX_ATTACHMENT_SIZE_BYTES", 1024)
    page_url = "http://example.test/notice/big"
    html = '<html><body><a href="/files/huge.pdf">huge.pdf</a></body></html>'
    mock_requests.get(page_url, text=html, headers={"Content-Type": "text/html"})
    mock_requests.get(
        "http://example.test/files/huge.pdf",
        content=b"%PDF-1.4 fake",
        headers={"Content-Type": "application/pdf", "Content-Length": "999999"},
    )

    result = url_loader.load_from_url(page_url)

    assert not result.attachments
    assert len(result.failed_attachments) == 1
    assert result.failed_attachments[0].error_code == "SIZE_LIMIT_EXCEEDED"


def test_attachment_streaming_bytes_exceed_limit_when_header_understates(mock_requests, monkeypatch):
    monkeypatch.setattr(url_loader, "MAX_ATTACHMENT_SIZE_BYTES", 50)
    page_url = "http://example.test/notice/lie"
    html = '<html><body><a href="/files/lie.pdf">lie.pdf</a></body></html>'
    mock_requests.get(page_url, text=html, headers={"Content-Type": "text/html"})
    # Content-Length는 5로 거짓 보고하지만 실제 본문은 200바이트 -> 스트리밍 누적 검사가 잡아야 함
    mock_requests.get(
        "http://example.test/files/lie.pdf",
        content=b"%" * 200,
        headers={"Content-Type": "application/pdf", "Content-Length": "5"},
    )

    result = url_loader.load_from_url(page_url)

    assert not result.attachments
    assert len(result.failed_attachments) == 1
    assert result.failed_attachments[0].error_code == "SIZE_LIMIT_EXCEEDED"


def test_max_attachments_limit_enforced(mock_requests, sample_pdf, monkeypatch):
    monkeypatch.setattr(url_loader, "MAX_ATTACHMENTS", 1)
    page_url = "http://example.test/notice/many"
    html = """
    <html><body>
      <a href="/files/a.pdf">a.pdf</a>
      <a href="/files/b.pdf">b.pdf</a>
    </body></html>
    """
    mock_requests.get(page_url, text=html, headers={"Content-Type": "text/html"})
    mock_requests.get("http://example.test/files/a.pdf", content=sample_pdf.read_bytes(), headers={"Content-Type": "application/pdf"})
    # b.pdf는 등록하지 않음 -> 상한 초과로 건너뛰어야 하며 실제 요청이 없어야 함

    result = url_loader.load_from_url(page_url)

    assert len(result.attachments) == 1
    assert len(result.failed_attachments) == 1
    assert result.failed_attachments[0].error_code == "ATTACHMENT_LIMIT_EXCEEDED"


# ---------------------------------------------------------------------------
# 형식 검증 (매직바이트)
# ---------------------------------------------------------------------------

def test_content_type_mismatch_rejected(mock_requests):
    page_url = "http://example.test/notice/mismatch"
    html = '<html><body><a href="/files/fake.pdf">fake.pdf</a></body></html>'
    mock_requests.get(page_url, text=html, headers={"Content-Type": "text/html"})
    # 확장자는 .pdf지만 실제로는 HTML 오류 페이지가 반환되는 경우
    mock_requests.get(
        "http://example.test/files/fake.pdf",
        content=b"<html><body>404 Not Found</body></html>",
        headers={"Content-Type": "application/pdf"},
    )

    result = url_loader.load_from_url(page_url)

    assert not result.attachments
    assert len(result.failed_attachments) == 1
    assert result.failed_attachments[0].error_code in ("CONTENT_TYPE_MISMATCH", "UNRECOGNIZED_FORMAT")


# ---------------------------------------------------------------------------
# SSRF / 리다이렉트 방어
# ---------------------------------------------------------------------------

def test_invalid_scheme_rejected(mock_requests):
    with pytest.raises(InvalidUrlError):
        url_loader.load_from_url("ftp://example.test/file.pdf")
    assert mock_requests.call_count == 0


@pytest.mark.parametrize("blocked_url", [
    "http://127.0.0.1/secret",
    "http://169.254.169.254/latest/meta-data/",
    "http://10.0.0.5/internal",
    "http://[::1]/secret",
])
def test_private_and_loopback_urls_are_blocked(mock_requests, blocked_url):
    with pytest.raises(BlockedUrlError):
        url_loader.load_from_url(blocked_url)
    assert mock_requests.call_count == 0


def test_redirect_to_private_ip_is_blocked(mock_requests):
    origin_url = "http://example.test/redirecting-page"
    mock_requests.get(origin_url, status_code=302, headers={"Location": "http://127.0.0.1/evil"})

    with pytest.raises(BlockedUrlError):
        url_loader.load_from_url(origin_url)


def test_too_many_redirects_raises(mock_requests):
    hops = [f"http://example.test/hop{i}" for i in range(6)]  # 6개 hop 전부 302 -> 5회 제한 초과
    for i, hop in enumerate(hops):
        next_hop = hops[i + 1] if i + 1 < len(hops) else "http://example.test/never-registered"
        mock_requests.get(hop, status_code=302, headers={"Location": next_hop})

    with pytest.raises(TooManyRedirectsError):
        url_loader.load_from_url(hops[0])


def test_redirects_are_not_auto_followed_by_requests(mock_requests):
    """allow_redirects=False로 요청했는지 확인 (매 hop을 코드가 직접 검증해야 하므로)"""
    origin_url = "http://example.test/one-redirect"
    target_url = "http://example.test/final-page"
    mock_requests.get(origin_url, status_code=302, headers={"Location": target_url})
    mock_requests.get(target_url, text="<html><body><p>ok</p></body></html>", headers={"Content-Type": "text/html"})

    result = url_loader.load_from_url(origin_url)

    assert result.page_content.url == target_url
    assert mock_requests.request_history[0].url == origin_url
    assert mock_requests.request_history[1].url == target_url


# ---------------------------------------------------------------------------
# 세션 재사용: 쿠키 유지 + Referer 설정
# ---------------------------------------------------------------------------

def test_session_cookies_and_referer_are_propagated_to_attachments(mock_requests, sample_pdf, monkeypatch):
    """
    requests_mock은 Set-Cookie 응답 헤더로부터 session.cookies를 실제로 채워주지 않는 한계가 있어
    (진짜 서버 대상으로는 requests.Session이 표준으로 처리하는 부분), 여기서는
    (1) 요청 전체 과정에서 requests.Session이 정확히 1회만 생성되어 재사용되는지,
    (2) 그 세션에 미리 심어둔 쿠키가 두 요청(페이지+첨부) 모두에 실려 가는지,
    (3) 첨부 요청에 원본 페이지 URL이 Referer로 설정되는지를 검증한다.
    """
    real_session_cls = requests.Session
    created_sessions = []

    class TrackedSession(real_session_cls):
        def __init__(self):
            super().__init__()
            self.cookies.set("sid", "abc123")
            created_sessions.append(self)

    monkeypatch.setattr(url_loader.requests, "Session", TrackedSession)

    page_url = "http://example.test/notice/session-test"
    html = '<html><body><a href="/files/a.pdf">a.pdf</a></body></html>'
    mock_requests.get(page_url, text=html, headers={"Content-Type": "text/html"})
    mock_requests.get(
        "http://example.test/files/a.pdf",
        content=sample_pdf.read_bytes(),
        headers={"Content-Type": "application/pdf"},
    )

    result = url_loader.load_from_url(page_url)

    assert len(result.attachments) == 1
    assert len(created_sessions) == 1  # 요청마다 새 세션을 만들지 않고 하나만 생성

    page_request, attachment_request = mock_requests.request_history[0], mock_requests.request_history[1]
    assert "sid=abc123" in page_request.headers.get("Cookie", "")
    assert "sid=abc123" in attachment_request.headers.get("Cookie", "")
    assert attachment_request.headers.get("Referer") == page_url


# ---------------------------------------------------------------------------
# attachment_finder 단위 테스트
# ---------------------------------------------------------------------------

def test_find_attachments_relative_url_resolution():
    html = '<html><body><a href="files/plan.pdf">plan</a></body></html>'
    candidates = attachment_finder.find_attachments(html, "http://example.test/notice/123")
    assert candidates[0].url == "http://example.test/notice/files/plan.pdf"


def test_find_attachments_deduplicates_same_url():
    html = """
    <html><body>
      <a href="/files/a.pdf">a (첫번째 링크)</a>
      <a href="/files/a.pdf">a (두번째 링크)</a>
    </body></html>
    """
    candidates = attachment_finder.find_attachments(html, "http://example.test/")
    assert len(candidates) == 1


def test_find_attachments_detects_extensionless_download_pattern():
    html = '<html><body><a href="/board/download.do?fileId=99">첨부파일</a></body></html>'
    candidates = attachment_finder.find_attachments(html, "http://example.test/")
    assert len(candidates) == 1
    assert "link_pattern" in candidates[0].discovery_reasons
    assert candidates[0].extension == AttachmentFileType.UNKNOWN


def test_find_attachments_anchor_text_extension_signal():
    html = '<html><body><a href="/board/view?seq=1">공고문.pptx</a></body></html>'
    candidates = attachment_finder.find_attachments(html, "http://example.test/")
    assert len(candidates) == 1
    assert candidates[0].extension == AttachmentFileType.PPTX
    assert "anchor_text_extension" in candidates[0].discovery_reasons


def test_find_attachments_ignores_plain_navigation_links():
    html = '<html><body><a href="/about">회사 소개</a></body></html>'
    candidates = attachment_finder.find_attachments(html, "http://example.test/")
    assert candidates == []


# ---------------------------------------------------------------------------
# html_parser 단위 테스트
# ---------------------------------------------------------------------------

def test_parse_html_extracts_structured_blocks():
    outcome = html_parser.parse_html(_SAMPLE_HTML)
    assert outcome.title == "2026년도 청년 창업 지원사업 공고"
    block_types = [b.block_type.value for b in outcome.blocks]
    assert "heading" in block_types
    assert "paragraph" in block_types
    assert "list" in block_types
    assert "table" in block_types


def test_parse_html_strips_script_and_style():
    html = "<html><body><script>evil()</script><style>.a{}</style><p>본문</p></body></html>"
    outcome = html_parser.parse_html(html)
    assert "evil" not in outcome.text
    assert outcome.text.strip() == "본문"


# ---------------------------------------------------------------------------
# file_downloader 단위 테스트
# ---------------------------------------------------------------------------

def test_sniff_file_signature_pdf(tmp_path, sample_pdf):
    dest = tmp_path / "x.bin"
    dest.write_bytes(sample_pdf.read_bytes())
    assert file_downloader.sniff_file_signature(dest) == "pdf"


def test_sniff_file_signature_docx(tmp_path, sample_docx):
    dest = tmp_path / "x.bin"
    dest.write_bytes(sample_docx.read_bytes())
    assert file_downloader.sniff_file_signature(dest) == "docx"


def test_sniff_file_signature_unknown(tmp_path):
    dest = tmp_path / "x.bin"
    dest.write_bytes(b"not a real document")
    assert file_downloader.sniff_file_signature(dest) == "unknown"


def test_validate_url_or_raise_blocks_loopback():
    with pytest.raises(BlockedUrlError):
        file_downloader.validate_url_or_raise("http://127.0.0.1/x")


def test_validate_url_or_raise_rejects_non_http_scheme():
    with pytest.raises(InvalidUrlError):
        file_downloader.validate_url_or_raise("file:///etc/passwd")


def test_guess_filename_from_content_disposition():
    class _FakeResponse:
        headers = {"Content-Disposition": 'attachment; filename="사업계획서.pdf"'}

    fetched = file_downloader.FetchedResponse.__new__(file_downloader.FetchedResponse)
    fetched.response = _FakeResponse()
    fetched.final_url = "http://example.test/download.do?fileId=1"

    name = file_downloader.guess_filename_from_response(fetched)
    assert name == "사업계획서.pdf"


def test_guess_filename_sanitizes_path_traversal():
    class _FakeResponse:
        headers = {"Content-Disposition": 'attachment; filename="../../etc/passwd"'}

    fetched = file_downloader.FetchedResponse.__new__(file_downloader.FetchedResponse)
    fetched.response = _FakeResponse()
    fetched.final_url = "http://example.test/download.do?fileId=1"

    name = file_downloader.guess_filename_from_response(fetched)
    assert name == "passwd"
    assert ".." not in name
