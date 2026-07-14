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

from ai.rag.loaders.config import MAX_ATTACHMENT_CANDIDATES, DOWNLOAD_LINK_PATTERNS
from ai.rag.loaders.schemas import AttachmentLinkInfo, AttachmentFileType

_EXTENSION_MAP = {
    "pdf": AttachmentFileType.PDF,
    "docx": AttachmentFileType.DOCX,
    "pptx": AttachmentFileType.PPTX,
    "hwp": AttachmentFileType.HWP,
    "hwpx": AttachmentFileType.HWPX,
}
_KNOWN_EXTENSIONS = tuple(_EXTENSION_MAP.keys())
_EXTENSION_IN_TEXT_RE = re.compile(r"\.(" + "|".join(_KNOWN_EXTENSIONS) + r")\b", re.IGNORECASE)
_IGNORED_HREF_PREFIXES = ("#", "javascript:", "mailto:", "tel:")


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

    ordered = _prioritize(list(candidates.values()))
    return ordered[:MAX_ATTACHMENT_CANDIDATES]


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
