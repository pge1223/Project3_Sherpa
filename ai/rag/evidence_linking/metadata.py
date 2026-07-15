"""
Evidence Metadata Extraction
================================
검색 결과 metadata(dict)에서 근거 표시에 필요한 필드를 안전하게 뽑아낸다.
metadata가 None/빈 dict이거나 필드가 없어도 예외를 던지지 않고 None을 반환한다.

페이지 번호는 다음 우선순위로 찾는다.
  1. "page_number" / "page" — 이미 사용자에게 보여줄 값(1-based)이라고 가정해 그대로 사용
  2. "location_number" — 현재 ai.rag.chunking.schemas.Chunk가 실제로 채우는 필드
     (ai/rag/parsers/pdf_parser.py에서 이미 1-based로 생성됨: page_num + 1)
  3. "page_index" — 이름상 0-based로 추정되는 필드이므로 표시용으로 +1 변환
"""

from typing import Optional

_DIRECT_PAGE_FIELDS: tuple[str, ...] = ("page_number", "page", "location_number")


def extract_document_title(metadata: Optional[dict]) -> Optional[str]:
    if not metadata:
        return None
    value = metadata.get("document_title")
    return value if value else None


def extract_section_title(metadata: Optional[dict]) -> Optional[str]:
    if not metadata:
        return None
    value = metadata.get("section_title")
    return value if value else None


def extract_content_kind(metadata: Optional[dict]) -> Optional[str]:
    if not metadata:
        return None
    value = metadata.get("content_kind")
    return str(value) if value is not None else None


def extract_page_number(metadata: Optional[dict]) -> Optional[int]:
    if not metadata:
        return None

    for field in _DIRECT_PAGE_FIELDS:
        value = metadata.get(field)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue

    page_index = metadata.get("page_index")
    if page_index is not None:
        try:
            return int(page_index) + 1
        except (TypeError, ValueError):
            return None

    return None
