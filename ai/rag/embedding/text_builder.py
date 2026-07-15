"""
Embedding Input Text Builder
==============================
Chroma에는 chunk.content 원문을 저장하지만, 임베딩 벡터는 document_title +
section_title + content를 결합한 텍스트로 생성한다 (검색 recall 향상 목적).
"""

from typing import Optional

_TITLE_LABEL = "문서 제목"
_SECTION_LABEL = "섹션"


def build_embedding_text(
    content: str,
    document_title: Optional[str] = None,
    section_title: Optional[str] = None,
) -> str:
    """
    "문서 제목: ...\n섹션: ...\n\n{content}" 형태로 결합한다.

    - None 또는 빈 문자열(공백만 포함)인 값은 제외한다.
    - document_title과 section_title이 서로 같으면 한 번만 쓴다.
    - document_title/section_title이 content와 완전히 같으면(중복 표시 방지) 헤더에서 뺀다.
    - 헤더로 쓸 값이 하나도 없으면 content만 그대로 반환한다.
    """
    normalized_content = content.strip()

    header_lines: list[str] = []
    seen_values: set[str] = set()
    for label, value in ((_TITLE_LABEL, document_title), (_SECTION_LABEL, section_title)):
        if value is None:
            continue
        normalized_value = value.strip()
        if not normalized_value:
            continue
        if normalized_value in seen_values:
            continue
        if normalized_value == normalized_content:
            continue
        seen_values.add(normalized_value)
        header_lines.append(f"{label}: {normalized_value}")

    if not header_lines:
        return normalized_content

    return "\n".join(header_lines) + "\n\n" + normalized_content
