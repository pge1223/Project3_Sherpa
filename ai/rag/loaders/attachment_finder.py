"""
Attachment Link Finder
======================
HTML 페이지에서 첨부파일(PDF/DOCX/PPTX/HWP/HWPX) 링크 후보를 탐색한다.

확장자만으로 판단하지 않고 다음 신호를 종합한다:
- href 확장자
- <a> 태그 표시 텍스트에 포함된 확장자 표기 (예: "붙임1.hwp")
- download 속성 (값에 확장자가 있으면 그것도 활용)
- URL 경로/쿼리스트링의 download/file/attach/atch 패턴 (확장자 없는 다운로드 링크 대응)

Content-Disposition 파일명과 실제 응답 Content-Type은 다운로드를 해야만 알 수 있는 신호이므로
여기서는 다루지 않고, url_loader.py가 다운로드 이후 최종 형식을 재확정한다.
"""

import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ai.rag.loaders.config import (
    MAX_ATTACHMENT_CANDIDATES,
    DOWNLOAD_LINK_PATTERNS,
    MIN_IMAGE_ATTACHMENT_DIMENSION_PX,
)
from ai.rag.loaders.schemas import AttachmentLinkInfo, AttachmentFileType

_EXTENSION_MAP = {
    "pdf": AttachmentFileType.PDF,
    "docx": AttachmentFileType.DOCX,
    "pptx": AttachmentFileType.PPTX,
    "hwp": AttachmentFileType.HWP,
    "hwpx": AttachmentFileType.HWPX,
    # 가은/Claude(2026-07-18): 공고 포스터 이미지 지원(url_loader.py의 이미지->PDF
    # 변환+OCR 재사용 경로) — jpg/jpeg는 같은 JPEG 형식으로 취급한다.
    "jpg": AttachmentFileType.JPEG,
    "jpeg": AttachmentFileType.JPEG,
    "png": AttachmentFileType.PNG,
}
_KNOWN_EXTENSIONS = tuple(_EXTENSION_MAP.keys())
_IMAGE_EXTENSIONS = ("jpg", "jpeg", "png")
_EXTENSION_IN_TEXT_RE = re.compile(r"\.(" + "|".join(_KNOWN_EXTENSIONS) + r")\b", re.IGNORECASE)
_IGNORED_HREF_PREFIXES = ("#", "javascript:", "mailto:", "tel:")
_IGNORED_IMG_SRC_PREFIXES = ("data:",)


def find_attachments(html_text: str, page_url: str) -> list[AttachmentLinkInfo]:
    """
    HTML 본문에서 첨부파일 링크 후보를 탐색해 절대 URL 기준으로 중복 제거 후 반환한다.
    확장자가 확정된 후보(pdf/docx/pptx/hwp/hwpx)를 우선하고, 개수는 설정된 상한으로 자른다.
    """
    soup = BeautifulSoup(html_text, "html.parser")
    candidates: dict[str, AttachmentLinkInfo] = {}

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"].strip()
        if not href or href.lower().startswith(_IGNORED_HREF_PREFIXES):
            continue

        absolute_url = urljoin(page_url, href)
        parsed = urlparse(absolute_url)
        if parsed.scheme not in ("http", "https"):
            continue

        anchor_text = a_tag.get_text(strip=True) or None
        has_download_attr = a_tag.has_attr("download")
        reasons: list[str] = []

        extension = _extension_from_path(parsed.path)
        if extension in _KNOWN_EXTENSIONS:
            reasons.append("href_extension")
        else:
            text_match = _EXTENSION_IN_TEXT_RE.search(anchor_text or "")
            if text_match:
                extension = text_match.group(1).lower()
                reasons.append("anchor_text_extension")

        if has_download_attr:
            reasons.append("download_attribute")
            if extension not in _KNOWN_EXTENSIONS:
                download_ext = _extension_from_path(a_tag.get("download") or "")
                if download_ext in _KNOWN_EXTENSIONS:
                    extension = download_ext

        if extension not in _KNOWN_EXTENSIONS:
            lowered_url = absolute_url.lower()
            if any(pattern in lowered_url for pattern in DOWNLOAD_LINK_PATTERNS):
                reasons.append("link_pattern")

        if not reasons:
            continue  # 첨부파일로 볼 근거가 전혀 없는 일반 링크

        file_type = _EXTENSION_MAP.get(extension, AttachmentFileType.UNKNOWN)
        file_name = _guess_file_name(parsed.path, anchor_text, extension)

        if absolute_url in candidates:
            existing = candidates[absolute_url]
            merged_reasons = list(dict.fromkeys(existing.discovery_reasons + reasons))
            resolved_type = existing.extension if existing.extension != AttachmentFileType.UNKNOWN else file_type
            candidates[absolute_url] = existing.model_copy(
                update={"discovery_reasons": merged_reasons, "extension": resolved_type}
            )
            continue

        candidates[absolute_url] = AttachmentLinkInfo(
            url=absolute_url,
            file_name=file_name,
            extension=file_type,
            anchor_text=anchor_text,
            discovery_reasons=reasons,
        )

    _find_image_candidates(soup, page_url, candidates)

    ordered = _prioritize(list(candidates.values()))
    return ordered[:MAX_ATTACHMENT_CANDIDATES]


# 가은/Claude(2026-07-18): 공모전 공고가 <a href="...pdf">처럼 다운로드 링크가 아니라
# <img src="포스터.jpg">로 페이지에 그냥 박혀 있는 경우가 많아서(실측: 정부기관 사이트) 추가.
# <a href>는 "명시적으로 걸어둔 첨부"라는 신호가 확실하지만, <img>는 로고/아이콘/공유버튼처럼
# 노이즈가 훨씬 많다 — 실측(sotong.go.kr)에서 width/height 속성 없는 img가 전부 통과돼
# logo.png/닫기버튼.png 등 4개가 쓸데없이 OCR까지 태워진 걸 확인했다. 크기 필터만으론
# 부족해서, "크기가 충분히 크다" 또는 "다운로드성 신호(부모 <a>가 첨부 패턴 링크, 또는
# 자기 URL 자체가 다운로드 패턴)가 있다" 둘 중 하나는 있어야 후보로 삼도록 강화한다.
# 트레이드오프: 크기 속성도 없고 다운로드 신호도 없는 "진짜 큰 콘텐츠 이미지"(반응형
# lazy-load 등)는 여전히 놓칠 수 있다 — 노이즈 억제를 recall보다 우선한 선택.
def _find_image_candidates(soup: BeautifulSoup, page_url: str, candidates: dict[str, AttachmentLinkInfo]) -> None:
    for img_tag in soup.find_all("img", src=True):
        src = img_tag["src"].strip()
        if not src or src.lower().startswith(_IGNORED_IMG_SRC_PREFIXES):
            continue

        absolute_url = urljoin(page_url, src)
        parsed = urlparse(absolute_url)
        if parsed.scheme not in ("http", "https"):
            continue
        if absolute_url in candidates:
            continue  # <a href>로 이미 잡힌 링크(썸네일이 첨부 링크를 감싸는 흔한 패턴)

        extension = _extension_from_path(parsed.path)
        if extension not in _IMAGE_EXTENSIONS:
            continue  # img 태그는 확장자가 이미지로 확정될 때만 후보로 삼는다(오탐 방지)

        if _looks_like_small_icon(img_tag):
            continue
        if not _has_attachment_signal(img_tag, absolute_url):
            continue

        anchor_text = img_tag.get("alt") or None
        candidates[absolute_url] = AttachmentLinkInfo(
            url=absolute_url,
            file_name=_guess_file_name(parsed.path, anchor_text, extension),
            extension=_EXTENSION_MAP[extension],
            anchor_text=anchor_text,
            discovery_reasons=["img_src_extension"],
        )


def _looks_like_small_icon(img_tag) -> bool:
    width = _parse_px_attr(img_tag.get("width"))
    height = _parse_px_attr(img_tag.get("height"))
    if width is None or height is None:
        return False  # 크기 정보가 없으면 이 필터만으론 판단 보류 (_has_attachment_signal이 이어받음)
    return width < MIN_IMAGE_ATTACHMENT_DIMENSION_PX and height < MIN_IMAGE_ATTACHMENT_DIMENSION_PX


def _has_attachment_signal(img_tag, absolute_url: str) -> bool:
    """명시적 크기(=충분히 큼, _looks_like_small_icon을 이미 통과)가 있으면 그 자체로
    충분한 신호로 본다. 크기 정보가 아예 없으면(레이지로딩 등 흔함), 부모 <a> 링크나
    자기 URL에 다운로드성 패턴이 있을 때만 통과시킨다 — 로고/아이콘류는 보통 이런 신호가
    없다."""
    width = _parse_px_attr(img_tag.get("width"))
    height = _parse_px_attr(img_tag.get("height"))
    if width is not None and height is not None:
        return True

    parent_link = img_tag.find_parent("a")
    if parent_link is not None:
        href = (parent_link.get("href") or "").lower()
        if any(pattern in href for pattern in DOWNLOAD_LINK_PATTERNS):
            return True
        if _extension_from_path(urlparse(href).path) in _KNOWN_EXTENSIONS:
            return True

    return any(pattern in absolute_url.lower() for pattern in DOWNLOAD_LINK_PATTERNS)


def _parse_px_attr(value: str | None) -> int | None:
    if not value:
        return None
    digits = "".join(ch for ch in value if ch.isdigit())
    return int(digits) if digits else None


def extension_from_url(url: str) -> str:
    """URL 경로에서 확장자를 유추한다 (없으면 빈 문자열). url_loader.py의 최초 판별에도 재사용된다."""
    return _extension_from_path(urlparse(url).path)


def _extension_from_path(path: str) -> str:
    if "." not in path:
        return ""
    ext = path.rsplit(".", 1)[-1].lower()
    if not ext.isalnum() or len(ext) > 5:
        return ""
    return ext


def _guess_file_name(path: str, anchor_text: str | None, extension: str) -> str:
    name = Path(path).name
    if name and "." in name:
        return name
    if anchor_text:
        match = _EXTENSION_IN_TEXT_RE.search(anchor_text)
        if match:
            return anchor_text.strip()
    return f"attachment.{extension}" if extension else "attachment"


def _prioritize(candidates: list[AttachmentLinkInfo]) -> list[AttachmentLinkInfo]:
    """확장자가 확정된 후보를 UNKNOWN(패턴 기반 추정) 후보보다 우선한다."""
    return sorted(candidates, key=lambda info: 0 if info.extension != AttachmentFileType.UNKNOWN else 1)
