from datetime import datetime, timezone

import pytest

from ai.rag.loaders.schemas import (
    FetchTargetType,
    WebBlockType,
    WebContentBlock,
    WebPageContent,
    UrlExtractionResult,
    AttachmentExtractionResult,
    UnsupportedAttachment,
    FailedAttachment,
)
from ai.rag.preprocessing.schemas import CleanedWebContent
from ai.rag.loaders.exceptions import (
    InvalidUrlError,
    BlockedUrlError,
    UrlFetchError,
    TooManyRedirectsError,
    DownloadSizeLimitExceededError,
)


def _make_page_content() -> WebPageContent:
    blocks = [
        WebContentBlock(content="공모전 안내", block_type=WebBlockType.HEADING, order=0),
        WebContentBlock(content="접수기간: 2026-03-01 ~ 2026-03-31", block_type=WebBlockType.PARAGRAPH, order=1),
    ]
    text = "\n\n".join(b.content for b in blocks)
    return WebPageContent(
        url="https://example.com/contest/1",
        title="공모전 안내 페이지",
        blocks=blocks,
        text=text,
        text_length=len(text),
        fetched_at=datetime.now(timezone.utc),
        encoding="utf-8",
        is_js_rendered_suspected=False,
    )


def _make_url_result(page_content=None, warnings=None) -> UrlExtractionResult:
    return UrlExtractionResult(
        origin_url="https://example.com/contest/1",
        fetch_target_type=FetchTargetType.HTML_PAGE if page_content else FetchTargetType.DIRECT_FILE,
        fetched_at=datetime.now(timezone.utc),
        page_content=page_content,
        attachments=[],
        unsupported_attachments=[UnsupportedAttachment(url="https://example.com/a.hwp", file_name="a.hwp", reason="미지원")],
        failed_attachments=[],
        warnings=warnings or [],
    )


def _make_cleaned(page_content: WebPageContent) -> CleanedWebContent:
    # 첫 블록(헤딩)은 노이즈로 제거된 것처럼 시뮬레이션
    kept = page_content.blocks[1:]
    return CleanedWebContent(
        source_url=page_content.url,
        original_block_count=len(page_content.blocks),
        cleaned_block_count=len(kept),
        cleaned_blocks=kept,
        removed_blocks=[],
        original_text_length=page_content.text_length,
        cleaned_text_length=sum(len(b.content) for b in kept),
        retention_ratio=0.5,
        fallback_used=False,
        warnings=[],
    )


@pytest.fixture(autouse=True)
def _patch_loader_and_cleaner(monkeypatch):
    calls = {"load_from_url": None, "clean_page_content_called": False}

    def _fake_load_from_url(url):
        calls["load_from_url"] = url
        page_content = _make_page_content()
        return _make_url_result(page_content=page_content, warnings=["HWP/HWPX 형식은 현재 미지원이며 다운로드/파싱하지 않습니다."])

    def _fake_clean_page_content(page_content):
        calls["clean_page_content_called"] = True
        return _make_cleaned(page_content)

    monkeypatch.setattr("app.api.routes.documents.load_from_url", _fake_load_from_url)
    monkeypatch.setattr("app.api.routes.documents.clean_page_content", _fake_clean_page_content)
    return calls


class TestFetchUrlSuccess:
    def test_returns_200(self, client, auth_header):
        resp = client.post("/documents/fetch-url", json={"url": "https://example.com/contest/1"}, headers=auth_header)
        assert resp.status_code == 200

    def test_load_from_url_called_with_request_url(self, client, auth_header, _patch_loader_and_cleaner):
        client.post("/documents/fetch-url", json={"url": "https://example.com/contest/1"}, headers=auth_header)
        assert _patch_loader_and_cleaner["load_from_url"] == "https://example.com/contest/1"

    def test_clean_page_content_called_when_page_content_present(self, client, auth_header, _patch_loader_and_cleaner):
        client.post("/documents/fetch-url", json={"url": "https://example.com/contest/1"}, headers=auth_header)
        assert _patch_loader_and_cleaner["clean_page_content_called"] is True

    def test_clean_page_content_not_called_when_page_content_absent(self, client, auth_header, monkeypatch):
        calls = {"clean_page_content_called": False}

        def _fake_load_no_page(url):
            return _make_url_result(page_content=None)

        def _fake_clean(page_content):
            calls["clean_page_content_called"] = True
            return _make_cleaned(page_content)

        monkeypatch.setattr("app.api.routes.documents.load_from_url", _fake_load_no_page)
        monkeypatch.setattr("app.api.routes.documents.clean_page_content", _fake_clean)

        resp = client.post("/documents/fetch-url", json={"url": "https://example.com/file.pdf"}, headers=auth_header)
        assert resp.status_code == 200
        assert resp.json()["page_content"] is None
        assert calls["clean_page_content_called"] is False

    def test_attachments_and_warnings_preserved(self, client, auth_header):
        resp = client.post("/documents/fetch-url", json={"url": "https://example.com/contest/1"}, headers=auth_header)
        body = resp.json()
        assert body["unsupported_attachments"][0]["file_name"] == "a.hwp"
        assert "HWP/HWPX" in body["warnings"][0]

    def test_response_matches_url_extraction_result_schema(self, client, auth_header):
        resp = client.post("/documents/fetch-url", json={"url": "https://example.com/contest/1"}, headers=auth_header)
        UrlExtractionResult.model_validate(resp.json())

    def test_cleaning_applied_but_other_fields_preserved(self, client, auth_header):
        resp = client.post("/documents/fetch-url", json={"url": "https://example.com/contest/1"}, headers=auth_header)
        body = resp.json()
        assert body["origin_url"] == "https://example.com/contest/1"
        assert body["page_content"]["title"] == "공모전 안내 페이지"  # cleaning 후에도 title 유지
        assert len(body["page_content"]["blocks"]) == 1  # 헤딩 블록 하나 제거된 정제 결과 반영


class TestFetchUrlErrors:
    def test_invalid_url_error_returns_400(self, client, auth_header, monkeypatch):
        def _raise(url):
            raise InvalidUrlError("URL 형식이 유효하지 않습니다")
        monkeypatch.setattr("app.api.routes.documents.load_from_url", _raise)
        resp = client.post("/documents/fetch-url", json={"url": "not-a-url"}, headers=auth_header)
        assert resp.status_code == 400

    def test_blocked_url_error_returns_400(self, client, auth_header, monkeypatch):
        def _raise(url):
            raise BlockedUrlError("내부 네트워크 URL은 허용되지 않습니다")
        monkeypatch.setattr("app.api.routes.documents.load_from_url", _raise)
        resp = client.post("/documents/fetch-url", json={"url": "http://127.0.0.1"}, headers=auth_header)
        assert resp.status_code == 400

    def test_too_many_redirects_error_returns_400(self, client, auth_header, monkeypatch):
        def _raise(url):
            raise TooManyRedirectsError("리다이렉트 허용 횟수를 초과했습니다")
        monkeypatch.setattr("app.api.routes.documents.load_from_url", _raise)
        resp = client.post("/documents/fetch-url", json={"url": "https://example.com/loop"}, headers=auth_header)
        assert resp.status_code == 400

    def test_url_fetch_error_returns_422(self, client, auth_header, monkeypatch):
        def _raise(url):
            raise UrlFetchError("네트워크 오류가 발생했습니다")
        monkeypatch.setattr("app.api.routes.documents.load_from_url", _raise)
        resp = client.post("/documents/fetch-url", json={"url": "https://example.com/timeout"}, headers=auth_header)
        assert resp.status_code == 422

    def test_download_size_limit_error_returns_422(self, client, auth_header, monkeypatch):
        def _raise(url):
            raise DownloadSizeLimitExceededError("파일 크기가 제한을 초과했습니다")
        monkeypatch.setattr("app.api.routes.documents.load_from_url", _raise)
        resp = client.post("/documents/fetch-url", json={"url": "https://example.com/huge"}, headers=auth_header)
        assert resp.status_code == 422

    def test_empty_url_returns_422(self, client, auth_header):
        resp = client.post("/documents/fetch-url", json={"url": ""}, headers=auth_header)
        assert resp.status_code == 422

    def test_unexpected_exception_returns_500(self, client, auth_header, monkeypatch):
        def _raise(url):
            raise RuntimeError("boom")
        monkeypatch.setattr("app.api.routes.documents.load_from_url", _raise)
        resp = client.post("/documents/fetch-url", json={"url": "https://example.com/contest/1"}, headers=auth_header)
        assert resp.status_code == 500
        assert resp.json()["detail"] == "URL 문서를 처리하는 중 오류가 발생했습니다."
        assert "Traceback" not in resp.text

    def test_missing_auth_header_rejected(self, client):
        resp = client.post("/documents/fetch-url", json={"url": "https://example.com/contest/1"})
        assert resp.status_code in (401, 422)


class TestRouterRegistration:
    def test_documents_router_registered_in_app(self, client):
        resp = client.get("/openapi.json")
        assert "/documents/fetch-url" in resp.json()["paths"]
