"""
URL-based Document Loader (Orchestrator)
========================================
공모전/정부지원사업 공고 URL을 입력받아:
  1. HTML 페이지인지 직접 파일 링크인지 판별
  2. HTML이면 본문을 구조화된 블록으로 추출 + 첨부파일 링크 탐색
  3. 첨부파일(PDF/DOCX/PPTX/JPEG/PNG)은 임시 다운로드 후 기존 ai.rag.parsers.UnifiedParser로
     전달(이미지는 1페이지 PDF로 변환해 기존 PDF+OCR 경로를 재사용, headless_renderer.py 참고)
  4. HWP/HWPX는 다운로드하지 않고 미지원으로 기록
  5. JS/AJAX 렌더링 의심 페이지는 headless_renderer.py(Playwright)로 재렌더링을 시도하고,
     그마저 실패하면(브라우저 미설치/타임아웃 등) 정적 결과 + 경고로 폴백한다(2026-07-18 추가
     — 실측: sotong.go.kr의 실제 진행 중 공고 페이지가 정적 fetch로는 "로딩 중..."만
     긁혀왔음)
  6. 처리 후 임시 파일은 항상 삭제

ai.rag.parsers 코드는 전혀 수정하지 않고, extract_document()만 재사용한다.
"""

import logging
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from PIL import Image

from ai.rag.parsers import extract_document
from ai.rag.parsers.exceptions import ParserError

from ai.rag.loaders.config import (
    MAX_ATTACHMENTS,
    MAX_ATTACHMENT_SIZE_BYTES,
    MAX_HTML_PAGE_SIZE_BYTES,
    MAX_TOTAL_DOWNLOAD_SIZE_BYTES,
    MIN_RENDERED_TEXT_LENGTH_AFTER_HEADLESS,
)
from ai.rag.loaders.exceptions import (
    InvalidUrlError,
    BlockedUrlError,
    UrlFetchError,
    TooManyRedirectsError,
    DownloadSizeLimitExceededError,
    HeadlessRenderError,
)
from ai.rag.loaders.file_downloader import (
    FetchedResponse,
    PeekedStream,
    validate_url_or_raise,
    open_stream,
    peek_stream,
    consume_peeked_as_text,
    consume_peeked_to_file,
    guess_filename_from_response,
    sniff_file_signature,
)
from ai.rag.loaders.headless_renderer import render_with_headless_browser
from ai.rag.loaders.html_parser import parse_html
from ai.rag.loaders.attachment_finder import find_attachments, extension_from_url

logger = logging.getLogger(__name__)
from ai.rag.loaders.schemas import (
    FetchTargetType,
    AttachmentFileType,
    WebPageContent,
    AttachmentLinkInfo,
    AttachmentExtractionResult,
    UnsupportedAttachment,
    FailedAttachment,
    UrlExtractionResult,
)

_UNSUPPORTED_EXTENSIONS = (AttachmentFileType.HWP, AttachmentFileType.HWPX)
_UNSUPPORTED_REASON = "HWP/HWPX 형식은 현재 미지원이며 다운로드/파싱하지 않습니다."


class _BudgetTracker:
    """URL 1건 처리 동안의 전체 다운로드 예산(기본 50MB)을 추적"""

    def __init__(self, total_bytes: int):
        self.remaining = total_bytes

    def commit(self, used_bytes: int) -> None:
        self.remaining = max(0, self.remaining - used_bytes)


def load_from_url(url: str) -> UrlExtractionResult:
    """
    URL을 수집하여 웹페이지 본문 + 첨부파일 파싱 결과를 반환한다.

    Raises:
        InvalidUrlError: URL 스킴/형식이 유효하지 않음
        BlockedUrlError: 사설/루프백/링크로컬 등 SSRF 차단 대상
        UrlFetchError: 원본 URL 자체를 가져오는 데 실패 (타임아웃/연결 오류 등)
        TooManyRedirectsError: 원본 URL 리다이렉트 초과
    """
    validate_url_or_raise(url)

    origin_ext = extension_from_url(url)
    fetched_at = datetime.now(timezone.utc)
    warnings: list[str] = []

    # HWP/HWPX를 가리키는 URL은 네트워크 요청 없이 즉시 미지원 처리
    if origin_ext in ("hwp", "hwpx"):
        return UrlExtractionResult(
            origin_url=url,
            fetch_target_type=FetchTargetType.DIRECT_FILE,
            fetched_at=fetched_at,
            page_content=None,
            attachments=[],
            unsupported_attachments=[
                UnsupportedAttachment(url=url, file_name=Path(urlparse(url).path).name or url, reason=_UNSUPPORTED_REASON)
            ],
            warnings=[_UNSUPPORTED_REASON],
        )

    session = requests.Session()
    budget = _BudgetTracker(MAX_TOTAL_DOWNLOAD_SIZE_BYTES)

    try:
        with tempfile.TemporaryDirectory(prefix="url_loader_") as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)

            fetched = open_stream(session, url)
            # 이 시점엔 HTML/직접파일 여부를 아직 모르므로 두 제한 중 큰 쪽으로 우선 peek하고,
            # 실제 소비(consume) 단계에서 각 경로에 맞는 정확한 제한을 다시 적용한다.
            peek_budget = min(max(MAX_ATTACHMENT_SIZE_BYTES, MAX_HTML_PAGE_SIZE_BYTES), budget.remaining)
            try:
                peeked = peek_stream(fetched, max_size_bytes=peek_budget)
            except DownloadSizeLimitExceededError as exc:
                raise UrlFetchError(f"원본 페이지 크기가 제한을 초과합니다: {exc}") from exc

            content_type = fetched.headers.get("Content-Type", "").split(";")[0].strip().lower()

            if _looks_like_direct_file(content_type, origin_ext, peeked.first_chunk):
                return _handle_direct_file(
                    origin_url=url,
                    fetched=fetched,
                    peeked=peeked,
                    origin_ext=origin_ext,
                    fetched_at=fetched_at,
                    budget=budget,
                    tmp_dir=tmp_dir,
                )

            return _handle_html_page(
                session=session,
                origin_url=url,
                fetched=fetched,
                peeked=peeked,
                fetched_at=fetched_at,
                budget=budget,
                tmp_dir=tmp_dir,
            )
    finally:
        session.close()


def _looks_like_direct_file(content_type: str, origin_ext: str, peek_bytes: bytes) -> bool:
    """실제 응답 Content-Type + 확장자 + 본문 바이트로 HTML 페이지 여부를 판별 (HEAD 결과는 사용하지 않음)"""
    if "html" in content_type:
        return False
    if any(
        marker in content_type
        for marker in ("pdf", "officedocument", "zip", "x-hwp", "octet-stream", "image/jpeg", "image/png")
    ):
        return True
    if origin_ext in ("pdf", "docx", "pptx", "hwp", "hwpx", "jpg", "jpeg", "png"):
        return True

    head = peek_bytes.lstrip()[:200].lower()
    if head.startswith(b"<!doctype html") or head.startswith(b"<html") or b"<head" in head:
        return False

    # Content-Type이 없거나 애매하고, 텍스트로도 보이지 않으면 바이너리(파일)로 취급
    if not content_type:
        return not _looks_like_text(peek_bytes)

    return False


def _looks_like_text(peek_bytes: bytes) -> bool:
    if not peek_bytes:
        return True
    try:
        peek_bytes.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def _handle_direct_file(
    *,
    origin_url: str,
    fetched: FetchedResponse,
    peeked: PeekedStream,
    origin_ext: str,
    fetched_at: datetime,
    budget: _BudgetTracker,
    tmp_dir: Path,
) -> UrlExtractionResult:
    declared_type = {
        "pdf": AttachmentFileType.PDF,
        "docx": AttachmentFileType.DOCX,
        "pptx": AttachmentFileType.PPTX,
        "hwp": AttachmentFileType.HWP,
        "hwpx": AttachmentFileType.HWPX,
        "jpg": AttachmentFileType.JPEG,
        "jpeg": AttachmentFileType.JPEG,
        "png": AttachmentFileType.PNG,
    }.get(origin_ext, AttachmentFileType.UNKNOWN)

    file_name_hint = Path(urlparse(origin_url).path).name or "download"
    candidate = AttachmentLinkInfo(
        url=origin_url,
        file_name=file_name_hint,
        extension=declared_type,
        anchor_text=None,
        discovery_reasons=["origin_url"],
    )

    attachment_result, unsupported, failed = _finalize_download(
        candidate=candidate,
        source_page_url=origin_url,
        fetched=fetched,
        peeked=peeked,
        budget=budget,
        tmp_dir=tmp_dir,
    )

    warnings: list[str] = []
    if unsupported is not None:
        warnings.append(unsupported.reason)

    return UrlExtractionResult(
        origin_url=origin_url,
        fetch_target_type=FetchTargetType.DIRECT_FILE,
        fetched_at=fetched_at,
        page_content=None,
        attachments=[attachment_result] if attachment_result else [],
        unsupported_attachments=[unsupported] if unsupported else [],
        failed_attachments=[failed] if failed else [],
        warnings=warnings,
    )


def _handle_html_page(
    *,
    session: requests.Session,
    origin_url: str,
    fetched: FetchedResponse,
    peeked: PeekedStream,
    fetched_at: datetime,
    budget: _BudgetTracker,
    tmp_dir: Path,
) -> UrlExtractionResult:
    final_url = fetched.final_url
    text, encoding = consume_peeked_as_text(peeked, max_size_bytes=min(MAX_HTML_PAGE_SIZE_BYTES, budget.remaining))
    budget.commit(len(text.encode(encoding, errors="replace")))

    outcome = parse_html(text)

    warnings: list[str] = []
    # 가은/Claude(2026-07-18): 정적 fetch가 JS/AJAX 렌더링 의심으로 판정되면(html_parser.py
    # _detect_js_rendered_suspected — "로딩 중..." placeholder 등), 실측(sotong.go.kr)에서
    # 확인한 대로 정적 텍스트만으로는 실제 콘텐츠를 영영 못 가져온다. 여기서만(항상 타지
    # 않음 — 비용이 크므로) Playwright로 다시 렌더링해서 재파싱한다. 렌더링 자체가
    # 실패해도(브라우저 미설치, 타임아웃 등) 요청 전체를 실패시키지 않고 기존 정적 결과 +
    # 경고로 안전하게 폴백한다.
    if outcome.is_js_rendered_suspected:
        try:
            rendered_html = render_with_headless_browser(final_url)
            rendered_outcome = parse_html(rendered_html)
            text = rendered_html
            outcome = rendered_outcome
            # 가은/Claude(2026-07-18): rendered_outcome.is_js_rendered_suspected를 그대로
            # "재판정"에 재사용하지 않는다 — 메인 콘텐츠는 다 채워졌는데 페이지 하단의
            # 별개 위젯("관련 글 더보기" 등)이 계속 "로딩 중..."이라 이 휴리스틱이 계속
            # True를 내는 걸 실측 확인함(config.py MIN_RENDERED_TEXT_LENGTH_AFTER_HEADLESS
            # 주석 참고). 렌더링된 본문 길이만으로 단순 판정한다.
            if len(rendered_outcome.text.strip()) < MIN_RENDERED_TEXT_LENGTH_AFTER_HEADLESS:
                warnings.append(
                    "이 페이지는 JavaScript 렌더링이 필요해 헤드리스 브라우저로 다시 불러왔지만, "
                    "그 이후에도 본문이 충분히 채워지지 않았습니다(콘텐츠가 없거나 상호작용이 더 필요할 수 있음)."
                )
        except HeadlessRenderError as exc:
            logger.warning("헤드리스 브라우저 렌더링 실패, 정적 fetch 결과로 폴백합니다: %s", exc)
            warnings.append(
                "이 페이지는 JavaScript 렌더링(SPA)으로 동작할 가능성이 있어 본문이 불완전하게 추출되었을 수 있습니다. "
                f"헤드리스 브라우저 재시도도 실패했습니다: {exc}"
            )

    page_content = WebPageContent(
        url=final_url,
        title=outcome.title,
        blocks=outcome.blocks,
        text=outcome.text,
        text_length=len(outcome.text),
        fetched_at=fetched_at,
        encoding=encoding,
        is_js_rendered_suspected=outcome.is_js_rendered_suspected,
    )

    candidates = find_attachments(text, final_url)

    attachments: list[AttachmentExtractionResult] = []
    unsupported_attachments: list[UnsupportedAttachment] = []
    failed_attachments: list[FailedAttachment] = []

    processed_count = 0
    for candidate in candidates:
        if candidate.extension in _UNSUPPORTED_EXTENSIONS:
            unsupported_attachments.append(
                UnsupportedAttachment(url=candidate.url, file_name=candidate.file_name, reason=_UNSUPPORTED_REASON)
            )
            continue

        if processed_count >= MAX_ATTACHMENTS:
            failed_attachments.append(FailedAttachment(
                url=candidate.url,
                file_name=candidate.file_name,
                error_code="ATTACHMENT_LIMIT_EXCEEDED",
                message=f"첨부파일 처리 상한({MAX_ATTACHMENTS}개)을 초과하여 건너뜁니다.",
            ))
            continue
        processed_count += 1

        attachment_result, unsupported, failed = _download_and_process_attachment(
            session=session,
            candidate=candidate,
            source_page_url=final_url,
            referer=final_url,
            budget=budget,
            tmp_dir=tmp_dir,
        )
        if attachment_result is not None:
            attachments.append(attachment_result)
        if unsupported is not None:
            unsupported_attachments.append(unsupported)
        if failed is not None:
            failed_attachments.append(failed)

    if unsupported_attachments:
        warnings.append(_UNSUPPORTED_REASON)

    return UrlExtractionResult(
        origin_url=origin_url,
        fetch_target_type=FetchTargetType.HTML_PAGE,
        fetched_at=fetched_at,
        page_content=page_content,
        attachments=attachments,
        unsupported_attachments=unsupported_attachments,
        failed_attachments=failed_attachments,
        warnings=warnings,
    )


def _download_and_process_attachment(
    *,
    session: requests.Session,
    candidate: AttachmentLinkInfo,
    source_page_url: str,
    referer: str,
    budget: _BudgetTracker,
    tmp_dir: Path,
) -> tuple[AttachmentExtractionResult | None, UnsupportedAttachment | None, FailedAttachment | None]:
    if budget.remaining <= 0:
        return None, None, FailedAttachment(
            url=candidate.url,
            file_name=candidate.file_name,
            error_code="TOTAL_SIZE_BUDGET_EXCEEDED",
            message="URL 1건 처리의 전체 다운로드 예산을 초과하여 건너뜁니다.",
        )

    try:
        fetched = open_stream(session, candidate.url, referer=referer)
        peeked = peek_stream(fetched, max_size_bytes=min(MAX_ATTACHMENT_SIZE_BYTES, budget.remaining))
    except InvalidUrlError as exc:
        return None, None, FailedAttachment(url=candidate.url, file_name=candidate.file_name, error_code="INVALID_URL", message="첨부파일 URL 형식이 유효하지 않습니다.")
    except BlockedUrlError:
        return None, None, FailedAttachment(url=candidate.url, file_name=candidate.file_name, error_code="BLOCKED_URL", message="내부/사설 네트워크 대상 URL이라 처리하지 않습니다.")
    except TooManyRedirectsError:
        return None, None, FailedAttachment(url=candidate.url, file_name=candidate.file_name, error_code="TOO_MANY_REDIRECTS", message="리다이렉트 허용 횟수를 초과했습니다.")
    except DownloadSizeLimitExceededError:
        return None, None, FailedAttachment(url=candidate.url, file_name=candidate.file_name, error_code="SIZE_LIMIT_EXCEEDED", message="파일 크기가 제한을 초과하여 다운로드를 중단했습니다.")
    except UrlFetchError:
        return None, None, FailedAttachment(url=candidate.url, file_name=candidate.file_name, error_code="FETCH_FAILED", message="첨부파일을 가져오는 중 네트워크 오류가 발생했습니다.")

    return _finalize_download(
        candidate=candidate,
        source_page_url=source_page_url,
        fetched=fetched,
        peeked=peeked,
        budget=budget,
        tmp_dir=tmp_dir,
    )


# 가은/Claude(2026-07-18): 다운로드한 이미지(포스터 등)를 1페이지 PDF로 감싼다 — 새 OCR
# 엔트리포인트를 만드는 대신, PDFParser가 이미 하는 "PDF 안에 박힌 이미지는 EasyOCR로
# 읽는다"(PR #6) 경로를 그대로 태우기 위함. 변환 자체는 Pillow로 충분하다(easyocr/pymupdf가
# 이미 물고 들어오는 의존성이라 새 패키지 추가 없음).
def _convert_image_to_pdf(image_path: Path, pdf_path: Path) -> None:
    with Image.open(image_path) as img:
        img.convert("RGB").save(pdf_path, "PDF", resolution=200.0)


def _finalize_download(
    *,
    candidate: AttachmentLinkInfo,
    source_page_url: str,
    fetched: FetchedResponse,
    peeked: PeekedStream,
    budget: _BudgetTracker,
    tmp_dir: Path,
) -> tuple[AttachmentExtractionResult | None, UnsupportedAttachment | None, FailedAttachment | None]:
    dest_path = tmp_dir / f"{uuid.uuid4().hex}_{candidate.file_name}"
    max_size = min(MAX_ATTACHMENT_SIZE_BYTES, budget.remaining)

    try:
        downloaded_bytes = consume_peeked_to_file(peeked, dest_path, max_size_bytes=max_size)
        budget.commit(downloaded_bytes)
    except DownloadSizeLimitExceededError:
        return None, None, FailedAttachment(
            url=candidate.url, file_name=candidate.file_name,
            error_code="SIZE_LIMIT_EXCEEDED",
            message="파일 크기가 제한을 초과하여 다운로드를 중단했습니다.",
        )

    try:
        final_file_name = guess_filename_from_response(fetched, fallback=candidate.file_name)
    except Exception:
        final_file_name = candidate.file_name

    sniffed = sniff_file_signature(dest_path)
    declared_ext = candidate.extension.value if candidate.extension != AttachmentFileType.UNKNOWN else None

    if sniffed in ("hwp_legacy", "hwpx"):
        # 확장자 없는 다운로드 링크가 실제로는 HWP/HWPX였던 경우: 미지원으로만 기록하고 파싱하지 않음
        dest_path.unlink(missing_ok=True)
        return None, UnsupportedAttachment(url=candidate.url, file_name=final_file_name, reason=_UNSUPPORTED_REASON), None

    typed_path = dest_path.with_suffix(f".{sniffed}")

    if sniffed in ("jpeg", "png"):
        # 가은/Claude(2026-07-18): 공고 포스터 이미지 지원 — 1페이지 PDF로 변환해
        # extract_document()가 그대로 PDF 경로(임베디드 이미지 OCR)를 타게 한다.
        dest_path.rename(typed_path)
        pdf_path = typed_path.with_suffix(".pdf")
        try:
            _convert_image_to_pdf(typed_path, pdf_path)
        except Exception:
            return None, None, FailedAttachment(
                url=candidate.url, file_name=final_file_name,
                error_code="IMAGE_CONVERSION_FAILED",
                message="이미지를 PDF로 변환하지 못했습니다. 손상되었거나 지원하지 않는 이미지일 수 있습니다.",
            )
        finally:
            typed_path.unlink(missing_ok=True)
        typed_path = pdf_path
    elif sniffed not in ("pdf", "docx", "pptx"):
        dest_path.unlink(missing_ok=True)
        return None, None, FailedAttachment(
            url=candidate.url, file_name=final_file_name,
            error_code="UNRECOGNIZED_FORMAT",
            message="지원 형식(PDF/DOCX/PPTX/JPEG/PNG)으로 확인되지 않아 처리하지 않습니다.",
        )
    elif declared_ext and declared_ext in ("pdf", "docx", "pptx") and declared_ext != sniffed:
        dest_path.unlink(missing_ok=True)
        return None, None, FailedAttachment(
            url=candidate.url, file_name=final_file_name,
            error_code="CONTENT_TYPE_MISMATCH",
            message="선언된 형식과 실제 파일 시그니처가 일치하지 않아 처리하지 않습니다.",
        )
    else:
        dest_path.rename(typed_path)

    try:
        extraction = extract_document(typed_path)
    except ParserError:
        return None, None, FailedAttachment(
            url=candidate.url, file_name=final_file_name,
            error_code="PARSE_FAILED",
            message="첨부파일을 파싱하지 못했습니다. 손상되었거나 지원하지 않는 내용일 수 있습니다.",
        )
    finally:
        typed_path.unlink(missing_ok=True)

    return AttachmentExtractionResult(
        attachment_url=candidate.url,
        file_name=final_file_name,
        source_page_url=source_page_url,
        extraction=extraction,
    ), None, None
