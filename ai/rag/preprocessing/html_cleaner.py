"""
Rule-based HTML Content Cleaner
================================
UrlExtractionResult.page_content(WebPageContent)에서 RAG에 필요한 핵심 블록만
남기고, 상단 메뉴/추천 콘텐츠/뉴스레터/footer 등 노이즈를 제거한다.

- 원본 WebPageContent와 그 blocks는 절대 mutate하지 않는다 (읽기만 함).
- LLM 호출 없이 규칙 기반으로만 동작하며, 재현 가능하고 테스트 가능하다.
- section_segmenter / classifier / dedup 로직은 MVP 단계라 이 파일 내부
  함수로 유지한다 (필요해지면 별도 모듈로 분리).

판정 우선순위 (섹션 단위):
  1) heading이 REMOVE 키워드와 일치 -> REMOVE (KEEP 키워드는 검사하지 않음)
  2) heading이 KEEP 키워드와 일치 -> KEEP
  3) heading이 문서의 첫 번째 heading이면 -> KEEP (제목으로 간주)
  4) heading이 없는 preamble 섹션이 "메뉴형 나열" 구조면 -> REMOVE
  5) 그 외: 섹션 본문 텍스트에서 KEEP/REMOVE 키워드를 재검사
  6) 그래도 애매하면 UNKNOWN -> 기본 정책은 KEEP (+ warning)
"""

import re
from dataclasses import dataclass, field

from ai.rag.loaders.schemas import WebPageContent, WebContentBlock, WebBlockType
from ai.rag.preprocessing.schemas import CleanedWebContent, RemovedBlock, RemovalReason, CleaningMethod
from ai.rag.preprocessing.keywords import (
    KEEP_HEADING_KEYWORDS,
    REMOVE_HEADING_KEYWORDS,
    BLOCK_LEVEL_BOILERPLATE_MARKERS,
    BLOCK_LEVEL_BOILERPLATE_MAX_LENGTH,
    STRUCTURAL_NOISE_MAX_BLOCKS,
    STRUCTURAL_NOISE_MAX_BLOCK_LENGTH,
    PREAMBLE_MENU_KEYWORDS,
    PREAMBLE_STRONG_CORE_KEYWORDS,
    PREAMBLE_MENU_MIN_SIGNALS,
    PREAMBLE_DELIMITED_ITEM_MAX_LENGTH,
    PREAMBLE_DELIMITED_ITEM_MIN_COUNT,
    MIN_RETENTION_RATIO,
    MIN_MEANINGFUL_ORIGINAL_TEXT_LENGTH,
)

_REMOVE_REASON_BY_CATEGORY: dict[str, RemovalReason] = {
    "nav_menu": RemovalReason.NAV_MENU,
    "login_signup": RemovalReason.LOGIN_SIGNUP,
    "advertisement": RemovalReason.ADVERTISEMENT,
    "recommended_content": RemovalReason.RECOMMENDED_CONTENT,
    "newsletter": RemovalReason.NEWSLETTER,
    "company_info_footer": RemovalReason.COMPANY_INFO_FOOTER,
}


@dataclass
class _Section:
    """heading 블록 하나 + 다음 heading 전까지의 본문 블록들 (heading은 None일 수 있음: preamble)"""
    heading: WebContentBlock | None
    body: list[WebContentBlock] = field(default_factory=list)

    def all_blocks(self) -> list[WebContentBlock]:
        return ([self.heading] if self.heading is not None else []) + self.body


def clean_page_content(page: WebPageContent) -> CleanedWebContent:
    """
    WebPageContent를 규칙 기반으로 정제하여 CleanedWebContent를 반환한다.
    원본 page 및 page.blocks는 어떤 경우에도 수정하지 않는다.
    """
    warnings: list[str] = []
    original_blocks = page.blocks
    original_block_count = len(original_blocks)
    original_text_length = page.text_length

    sections = _segment_into_sections(original_blocks)

    kept_blocks: list[WebContentBlock] = []
    removed_blocks: list[RemovedBlock] = []
    first_heading_seen = False

    for section in sections:
        is_first_heading_section = False
        if section.heading is not None and not first_heading_seen:
            is_first_heading_section = True
            first_heading_seen = True

        decision, reason, detail = _classify_section(section, is_first_heading_section)

        if decision == "REMOVE":
            for block in section.all_blocks():
                removed_blocks.append(RemovedBlock(block=block, reason=reason, detail=detail))
            continue

        if decision == "UNKNOWN":
            heading_label = section.heading.content if section.heading else "(heading 없음)"
            warnings.append(
                f"섹션(heading='{heading_label}')이 규칙으로 분류되지 않아 기본 정책에 따라 유지되었습니다."
            )

        # KEEP 또는 UNKNOWN(->KEEP): heading은 그대로 유지, 본문은 개별 상용구 블록만 한 번 더 거름
        if section.heading is not None:
            kept_blocks.append(section.heading)

        filtered_body, boilerplate_removed = _filter_boilerplate_blocks(section.body)
        kept_blocks.extend(filtered_body)
        removed_blocks.extend(boilerplate_removed)

    deduped_blocks, duplicate_removed = _dedup_exact(kept_blocks)
    removed_blocks.extend(duplicate_removed)

    cleaned_blocks = deduped_blocks
    cleaned_text_length = sum(len(b.content) for b in cleaned_blocks)
    retention_ratio = (cleaned_text_length / original_text_length) if original_text_length > 0 else 0.0
    fallback_used = False

    if original_block_count > 0 and _should_fallback(cleaned_blocks, original_text_length, retention_ratio):
        fallback_used = True
        warnings.append(
            "정제 규칙이 대부분 또는 전체 블록을 제거 대상으로 판단했습니다. "
            "핵심 정보 손실 위험을 피하기 위해 원본 블록 전체를 유지하는 안전 모드(fallback)로 전환했습니다. "
            "키워드 사전 튜닝이 필요할 수 있습니다."
        )
        cleaned_blocks = list(original_blocks)
        removed_blocks = []
        cleaned_text_length = original_text_length
        retention_ratio = 1.0 if original_text_length > 0 else 0.0

    return CleanedWebContent(
        source_url=page.url,
        original_block_count=original_block_count,
        cleaned_block_count=len(cleaned_blocks),
        cleaned_blocks=cleaned_blocks,
        removed_blocks=removed_blocks,
        original_text_length=original_text_length,
        cleaned_text_length=cleaned_text_length,
        retention_ratio=retention_ratio,
        fallback_used=fallback_used,
        warnings=warnings,
        cleaning_method=CleaningMethod.RULE_BASED_V1,
    )


# ---------------------------------------------------------------------------
# 섹션 분할 (원본 blocks를 순서대로 순회, 모든 HEADING 블록을 새 섹션 시작점으로 처리)
# ---------------------------------------------------------------------------

def _segment_into_sections(blocks: list[WebContentBlock]) -> list[_Section]:
    sections: list[_Section] = []
    current: _Section | None = None

    for block in blocks:
        if block.block_type == WebBlockType.HEADING:
            if current is not None:
                sections.append(current)
            current = _Section(heading=block, body=[])
        else:
            if current is None:
                current = _Section(heading=None, body=[])
            current.body.append(block)

    if current is not None:
        sections.append(current)

    return sections


# ---------------------------------------------------------------------------
# 섹션 단위 분류
# ---------------------------------------------------------------------------

def _classify_section(
    section: _Section, is_first_heading_section: bool
) -> tuple[str, RemovalReason | None, str]:
    """Returns (decision, reason, detail). decision은 "KEEP" | "REMOVE" | "UNKNOWN" """
    heading_text = section.heading.content if section.heading else ""

    if section.heading is not None:
        remove_hit = _match_keywords(heading_text, REMOVE_HEADING_KEYWORDS)
        if remove_hit is not None:
            category, keyword = remove_hit
            return (
                "REMOVE",
                _REMOVE_REASON_BY_CATEGORY[category],
                f"heading '{heading_text}'이(가) 제거 키워드 '{keyword}'({category})와 일치",
            )

        keep_hit = _match_keywords(heading_text, KEEP_HEADING_KEYWORDS)
        if keep_hit is not None:
            category, keyword = keep_hit
            return (
                "KEEP",
                None,
                f"heading '{heading_text}'이(가) 유지 키워드 '{keyword}'({category})와 일치",
            )

        if is_first_heading_section:
            return "KEEP", None, f"heading '{heading_text}'이(가) 문서의 첫 heading으로 제목으로 간주됨"

    if section.heading is None and _looks_like_menu_preamble(section.body):
        return (
            "REMOVE",
            RemovalReason.UNCLASSIFIED_STRUCTURAL_NOISE,
            "heading 없이 문서 최상단에 위치한 짧은 항목 나열(메뉴형 구조)로 판단",
        )

    body_text = "\n".join(b.content for b in section.body)
    remove_hit = _match_keywords(body_text, REMOVE_HEADING_KEYWORDS)
    keep_hit = _match_keywords(body_text, KEEP_HEADING_KEYWORDS)

    if keep_hit is not None and remove_hit is None:
        category, keyword = keep_hit
        return "KEEP", None, f"heading 미매치, 본문에서 유지 키워드 '{keyword}'({category}) 발견"

    if remove_hit is not None and keep_hit is None:
        category, keyword = remove_hit
        return (
            "REMOVE",
            _REMOVE_REASON_BY_CATEGORY[category],
            f"heading 미매치, 본문에서 제거 키워드 '{keyword}'({category}) 발견",
        )

    return "UNKNOWN", None, "키워드/구조적 신호로 분류되지 않음"


def _match_keywords(text: str, keyword_map: dict[str, list[str]]) -> tuple[str, str] | None:
    normalized = text.lower()
    for category, keywords in keyword_map.items():
        for keyword in keywords:
            if keyword.lower() in normalized:
                return category, keyword
    return None


def _looks_like_menu_preamble(body: list[WebContentBlock]) -> bool:
    """
    heading 없는 첫 섹션(preamble)이 상단 메뉴/카테고리 나열인지 판단한다.

    여러 개의 독립적인 신호를 조합해 판단하며(단일 신호로는 제거하지 않음),
    "강한" 핵심 공고 키워드(PREAMBLE_STRONG_CORE_KEYWORDS)가 섞여 있으면 보수적으로 제거하지 않는다.
    이 가드는 TABLE 블록 여부와 무관하게 동일하게 적용되므로, TABLE도 강한 키워드가
    있을 때만 보호되고 강한 키워드 없는 TABLE은 일반 블록과 동일하게 평가된다.

    주의: 이 가드에는 KEEP_HEADING_KEYWORDS 전체가 아니라 PREAMBLE_STRONG_CORE_KEYWORDS만
    사용한다. "시상"처럼 짧고 일반적인 KEEP 키워드는 "시상식 갤러리" 같은 메뉴 라벨에도
    흔히 등장해, 이를 그대로 쓰면 실제 메뉴를 "핵심 정보 있음"으로 오판해 제거를 막아버린다.
    """
    if not body:
        return False

    combined_text = "\n".join(block.content for block in body)

    if _contains_any(combined_text, PREAMBLE_STRONG_CORE_KEYWORDS):
        return False

    has_consecutive_lists = _has_consecutive_list_blocks(body, min_consecutive=2)
    menu_keyword_hits = _count_keyword_hits(combined_text, PREAMBLE_MENU_KEYWORDS)

    # 명시 규칙: LIST 2개 이상 + 메뉴 키워드 2개 이상 + (위에서 이미 확인된) 강한 핵심 키워드 없음
    # -> 다른 약한 신호가 부족해도 메뉴로 판단해 제거한다.
    if has_consecutive_lists and menu_keyword_hits >= 2:
        return True

    signals = 0

    # 신호 1: 모든 블록이 매우 짧음 (기존 판정 방식)
    if len(body) <= STRUCTURAL_NOISE_MAX_BLOCKS and all(
        len(block.content.strip()) <= STRUCTURAL_NOISE_MAX_BLOCK_LENGTH for block in body
    ):
        signals += 1

    # 신호 2: LIST 블록이 2개 이상 연속으로 등장 (메뉴가 리스트 여러 개로 쪼개져 추출된 경우)
    if has_consecutive_lists:
        signals += 1

    # 신호 3: 메뉴/카테고리성 키워드가 2회 이상 반복 등장
    if menu_keyword_hits >= 2:
        signals += 1

    # 신호 4: 여러 메뉴 항목이 한 블록에 -, /, 줄바꿈 등으로 나열되어 추출된 경우
    if _looks_like_delimited_menu_items(combined_text):
        signals += 1

    return signals >= PREAMBLE_MENU_MIN_SIGNALS


def _contains_any(text: str, keywords: list[str]) -> bool:
    normalized = text.lower()
    return any(keyword.lower() in normalized for keyword in keywords)


def _has_consecutive_list_blocks(body: list[WebContentBlock], min_consecutive: int) -> bool:
    run = 0
    for block in body:
        if block.block_type == WebBlockType.LIST:
            run += 1
            if run >= min_consecutive:
                return True
        else:
            run = 0
    return False


def _count_keyword_hits(text: str, keywords: list[str]) -> int:
    normalized = text.lower()
    return sum(1 for keyword in keywords if keyword.lower() in normalized)


def _looks_like_delimited_menu_items(text: str) -> bool:
    """'- 공모전 / 대외활동 / 이벤트' 처럼 한 블록에 여러 짧은 메뉴 항목이 붙어 추출된 경우를 탐지"""
    tokens = re.split(r"[\-/\n]", text)
    short_tokens = [t.strip() for t in tokens if t.strip() and len(t.strip()) <= PREAMBLE_DELIMITED_ITEM_MAX_LENGTH]
    return len(short_tokens) >= PREAMBLE_DELIMITED_ITEM_MIN_COUNT


# ---------------------------------------------------------------------------
# KEEP 섹션 내부에 섞인 개별 상용구 블록 제거
# ---------------------------------------------------------------------------

def _filter_boilerplate_blocks(
    body: list[WebContentBlock],
) -> tuple[list[WebContentBlock], list[RemovedBlock]]:
    kept: list[WebContentBlock] = []
    removed: list[RemovedBlock] = []

    for block in body:
        normalized = block.content.strip()
        is_boilerplate = (
            len(normalized) <= BLOCK_LEVEL_BOILERPLATE_MAX_LENGTH
            and any(marker.lower() in normalized.lower() for marker in BLOCK_LEVEL_BOILERPLATE_MARKERS)
        )
        if is_boilerplate:
            removed.append(RemovedBlock(
                block=block,
                reason=RemovalReason.COMPANY_INFO_FOOTER,
                detail=f"유지 섹션 내부에 섞인 상용구 블록으로 판단 (내용: '{normalized[:40]}')",
            ))
        else:
            kept.append(block)

    return kept, removed


# ---------------------------------------------------------------------------
# 정확 중복 제거 (근사 중복은 MVP 범위 밖 — 별도 기능으로 추가 예정)
# ---------------------------------------------------------------------------

def _dedup_exact(blocks: list[WebContentBlock]) -> tuple[list[WebContentBlock], list[RemovedBlock]]:
    seen: set[str] = set()
    kept: list[WebContentBlock] = []
    removed: list[RemovedBlock] = []

    for block in blocks:
        normalized = " ".join(block.content.split()).lower()
        if normalized and normalized in seen:
            removed.append(RemovedBlock(
                block=block,
                reason=RemovalReason.DUPLICATE,
                detail="문서 내 동일 내용 블록이 이미 앞에서 유지되어 중복 제거됨",
            ))
            continue
        if normalized:
            seen.add(normalized)
        kept.append(block)

    return kept, removed


# ---------------------------------------------------------------------------
# fallback(안전 모드) 판단
# ---------------------------------------------------------------------------

def _should_fallback(
    cleaned_blocks: list[WebContentBlock], original_text_length: int, retention_ratio: float
) -> bool:
    if len(cleaned_blocks) == 0:
        return True
    if original_text_length >= MIN_MEANINGFUL_ORIGINAL_TEXT_LENGTH and retention_ratio < MIN_RETENTION_RATIO:
        return True
    return False
