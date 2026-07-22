# 작성자: 재인/Claude (2026-07-21)
# 목적: DocumentBlock 목록(파서 공통 산출물)을 서식이 살아있는 HTML로 렌더링한다.
#   "AI 피드백" 워크벤치가 기획서 원문을 워드/한글처럼 보여주기 위해 추가 - 기존
#   parse()가 만드는 content(순수 텍스트, RAG 청킹·임베딩이 그대로 씀)는 안 건드리고,
#   docx_parser.py가 각 블록 metadata["runs"]에 추가로 남겨둔 굵게/기울임 정보를
#   읽어서 별도로 HTML을 만든다. content와 완전히 분리된 새 산출물이라, RAG
#   파이프라인이나 기존 parsed_text 사용처에는 아무 영향이 없다.
from __future__ import annotations

from html import escape

from ai.rag.parsers.schemas import BlockType, DocumentBlock

_TAG_BY_BLOCK_TYPE = {
    BlockType.TITLE: "h2",
    BlockType.LIST: "li",
    BlockType.TEXT: "p",
}


def _runs_to_html(runs: list[dict], fallback_text: str) -> str:
    """metadata["runs"]가 있으면 run 단위 굵게/기울임을 살려서, 없으면(표 등 runs를
    안 채우는 블록 타입) fallback_text를 이스케이프만 해서 반환한다."""
    if not runs:
        return escape(fallback_text)
    parts = []
    for run in runs:
        text = escape(run.get("text", ""))
        if run.get("bold"):
            text = f"<b>{text}</b>"
        if run.get("italic"):
            text = f"<i>{text}</i>"
        parts.append(text)
    return "".join(parts)


def render_blocks_to_html(blocks: list[DocumentBlock]) -> str:
    """블록 목록을 하나의 HTML 문자열로 합친다. 리스트 블록은 연속된 <li>를 <ul>로
    묶고, 표는 탭으로 구분된 content를 <table>로 재구성한다."""
    html_parts: list[str] = []
    in_list = False

    for block in blocks:
        if block.block_type == BlockType.LIST:
            if not in_list:
                html_parts.append("<ul>")
                in_list = True
        elif in_list:
            html_parts.append("</ul>")
            in_list = False

        if block.block_type == BlockType.TABLE:
            rows = [row.split("\t") for row in block.content.split("\n") if row.strip()]
            cells_html = "".join(
                "<tr>" + "".join(f"<td>{escape(cell)}</td>" for cell in row) + "</tr>"
                for row in rows
            )
            html_parts.append(f"<table>{cells_html}</table>")
            continue

        tag = _TAG_BY_BLOCK_TYPE.get(block.block_type, "p")
        runs = block.metadata.get("runs") if block.metadata else None
        content_html = _runs_to_html(runs, block.content)
        html_parts.append(f"<{tag}>{content_html}</{tag}>")

    if in_list:
        html_parts.append("</ul>")

    return "\n".join(html_parts)
