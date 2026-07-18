"""
Static HTML Page Parser
========================
정적 HTML 페이지에서 제목/본문을 청킹 가능한 구조로 추출한다.
is_js_rendered_suspected가 True면 url_loader.py가 headless_renderer.py(Playwright)로
다시 렌더링해서 재시도한다(2026-07-18 추가) — 이 함수 자체는 여전히 순수 정적 파싱만
한다(휴리스틱 판정 + 파싱 로직을 분리 유지).
"""

from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from ai.rag.loaders.config import LOADING_PLACEHOLDER_PATTERNS
from ai.rag.loaders.schemas import WebContentBlock, WebBlockType

_NOISE_TAGS = ("script", "style", "noscript", "nav", "header", "footer", "aside", "iframe", "svg")
_HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")
_BLOCK_TAGS = _HEADING_TAGS + ("p", "ul", "ol", "table")
_SPA_ROOT_IDS = ("app", "root", "__next", "__nuxt")


@dataclass
class HtmlParseOutcome:
    title: str | None
    blocks: list[WebContentBlock] = field(default_factory=list)
    text: str = ""
    is_js_rendered_suspected: bool = False


def parse_html(html_text: str) -> HtmlParseOutcome:
    """정적 HTML 문자열을 파싱하여 제목/구조화 블록/전체 텍스트/JS 렌더링 의심 여부를 반환한다."""
    soup = BeautifulSoup(html_text, "html.parser")

    title = None
    if soup.title and soup.title.string:
        title = soup.title.string.strip() or None

    js_rendered_suspected = _detect_js_rendered_suspected(soup, html_text)

    for tag in soup.find_all(_NOISE_TAGS):
        tag.decompose()

    body = soup.body or soup
    blocks = _extract_blocks(body)
    text = "\n\n".join(block.content for block in blocks)

    return HtmlParseOutcome(
        title=title,
        blocks=blocks,
        text=text,
        is_js_rendered_suspected=js_rendered_suspected,
    )


def _extract_blocks(body) -> list[WebContentBlock]:
    blocks: list[WebContentBlock] = []
    order = 0

    for element in body.find_all(_BLOCK_TAGS):
        # 테이블 내부의 p/heading 등은 별도 블록으로 중복 추출하지 않음
        if element.name != "table" and element.find_parent("table") is not None:
            continue

        if element.name in _HEADING_TAGS:
            text = element.get_text(strip=True)
            if not text:
                continue
            blocks.append(WebContentBlock(
                content=text,
                block_type=WebBlockType.HEADING,
                order=order,
                metadata={"level": int(element.name[1])},
            ))
            order += 1

        elif element.name == "p":
            text = element.get_text(strip=True)
            if not text:
                continue
            blocks.append(WebContentBlock(
                content=text,
                block_type=WebBlockType.PARAGRAPH,
                order=order,
                metadata={},
            ))
            order += 1

        elif element.name in ("ul", "ol"):
            items = [li.get_text(strip=True) for li in element.find_all("li", recursive=False)]
            items = [item for item in items if item]
            if not items:
                continue
            blocks.append(WebContentBlock(
                content="\n".join(f"- {item}" for item in items),
                block_type=WebBlockType.LIST,
                order=order,
                metadata={"list_type": element.name, "item_count": len(items)},
            ))
            order += 1

        elif element.name == "table":
            rows = []
            for tr in element.find_all("tr"):
                cells = [cell.get_text(strip=True) for cell in tr.find_all(["td", "th"])]
                if any(cells):
                    rows.append(" | ".join(cells))
            if not rows:
                continue
            blocks.append(WebContentBlock(
                content="\n".join(rows),
                block_type=WebBlockType.TABLE,
                order=order,
                metadata={"row_count": len(rows)},
            ))
            order += 1

    return blocks


def _detect_js_rendered_suspected(soup: BeautifulSoup, raw_html: str) -> bool:
    """
    JS 렌더링(SPA) 의심 휴리스틱. 확정 판정이 아니라 경고용 신호이다.

    다음 중 하나라도 해당하면 의심으로 판단:
    - #app/#root/#__next 등 SPA 루트 컨테이너가 있는데 텍스트가 거의 없음
    - <script> 태그 수는 많은데(10개 초과) 본문 텍스트가 거의 없음(500자 미만)
    - 원본 HTML 크기(5000자 초과)에 비해 본문 텍스트가 지나치게 적음(200자 미만)
    - 본문에 "로딩 중..." 같은 placeholder 문구가 있음 (2026-07-18 추가 — sotong.go.kr
      실측: 메뉴 등 주변 텍스트는 충분해서 위 텍스트-길이 기준은 통과하지만, 정작 본문
      영역만 AJAX로 나중에 채워지는 페이지를 놓치는 걸 확인함. 전체 SPA가 아니라 페이지
      일부 영역만 비동기로 채워지는 흔한 패턴이라 별도 신호로 둔다.)
    """
    body_text = soup.get_text(strip=True)
    body_text_length = len(body_text)
    script_count = len(soup.find_all("script"))

    for root_id in _SPA_ROOT_IDS:
        root_el = soup.find(id=root_id)
        if root_el is not None and len(root_el.get_text(strip=True)) < 50:
            return True

    if script_count > 10 and body_text_length < 500:
        return True

    if len(raw_html) > 5000 and body_text_length < 200:
        return True

    lowered_body_text = body_text.lower()
    if any(pattern.lower() in lowered_body_text for pattern in LOADING_PLACEHOLDER_PATTERNS):
        return True

    return False
