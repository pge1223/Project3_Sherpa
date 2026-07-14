"""
Tests for Rule-based HTML Content Cleaning (ai.rag.preprocessing)
==================================================================
네트워크를 전혀 사용하지 않고, WebPageContent를 직접 구성해 순수 함수로 테스트한다.
"""

import copy
from datetime import datetime, timezone

import pytest

from ai.rag.loaders.schemas import WebPageContent, WebContentBlock, WebBlockType
from ai.rag.preprocessing import clean_page_content
from ai.rag.preprocessing.schemas import RemovalReason


def _block(content: str, block_type: WebBlockType = WebBlockType.PARAGRAPH, order: int = 0, metadata: dict | None = None) -> WebContentBlock:
    return WebContentBlock(content=content, block_type=block_type, order=order, metadata=metadata or {})


def _heading(content: str, order: int, level: int = 2) -> WebContentBlock:
    return _block(content, block_type=WebBlockType.HEADING, order=order, metadata={"level": level})


def _page(blocks: list[WebContentBlock], url: str = "http://example.test/notice/1") -> WebPageContent:
    text = "\n\n".join(b.content for b in blocks)
    return WebPageContent(
        url=url,
        title="테스트 공고",
        blocks=blocks,
        text=text,
        text_length=len(text),
        fetched_at=datetime.now(timezone.utc),
        encoding="utf-8",
        is_js_rendered_suspected=False,
    )


def _assert_partition_invariants(page: WebPageContent, result):
    """공통 불변 조건: 개수 합, 순서 유지, 원본-정제/제거 집합 분할"""
    assert result.cleaned_block_count == len(result.cleaned_blocks)
    assert len(result.cleaned_blocks) + len(result.removed_blocks) == result.original_block_count == len(page.blocks)

    kept_ids = {id(b) for b in result.cleaned_blocks}
    removed_ids = {id(rb.block) for rb in result.removed_blocks}
    original_ids = {id(b) for b in page.blocks}

    assert kept_ids.isdisjoint(removed_ids)
    assert kept_ids | removed_ids == original_ids

    kept_orders = [b.order for b in result.cleaned_blocks]
    assert kept_orders == sorted(kept_orders)


# ---------------------------------------------------------------------------
# 실제 공모전 페이지를 흉내낸 종합 시나리오
# (thinkyou류 사이트: 상단 메뉴 preamble -> 제목 -> 핵심 섹션들 -> 추천 섹션 -> 문의(+footer 잔재))
# ---------------------------------------------------------------------------

def _build_contest_page() -> WebPageContent:
    blocks = [
        # preamble: 메뉴형 나열 (짧은 항목 다수, heading 없음)
        _block("홈", order=0),
        _block("공모전", order=1),
        _block("대외활동", order=2),
        _block("로그인", order=3),
        # 제목 (문서의 첫 heading)
        _heading("2026년도 청년 창업 아이디어 공모전", order=4, level=1),
        _block("본 공모전은 청년 창업가를 발굴하기 위해 개최됩니다.", order=5),
        # 핵심 섹션들
        _heading("주최 및 주관", order=6),
        _block("주최: 중소벤처기업부 / 주관: 청년창업진흥원", order=7),
        _heading("접수기간", order=8),
        _block("2026.08.01 ~ 2026.08.31", order=9),
        _heading("참가자격", order=10),
        _block("전국 만 19~39세 청년 누구나 참가 가능", order=11),
        _heading("공모주제", order=12),
        _block("지속가능한 지역 문제 해결형 창업 아이디어", order=13),
        _heading("제출방법", order=14),
        _block("이메일 접수 (contest@example.org)", order=15),
        _block("이용약관 | 개인정보처리방침 | 사업자등록번호: 123-45-67890", order=16),  # KEEP 섹션에 섞인 footer 잔재
        _heading("심사기준", order=17),
        _block("창의성 40%, 실현가능성 30%, 파급효과 30%", order=18),
        _heading("시상내역", order=19),
        _block("대상 1팀 상금 500만원", order=20),
        # 노이즈 섹션: heading이 REMOVE 키워드와 매치되면 본문에 KEEP 키워드가 있어도 통째로 제거되어야 함
        _heading("함께 보면 좋은 공모전", order=21),
        _block("[2026 대학생 아이디어 공모전] 접수기간: 2026.09.01 ~ 2026.09.30", order=22),
        _block("[전국 사진 공모전] 참가자격: 전국민 누구나", order=23),
        # 문의처 (전화번호 포함 -> heading이 KEEP 키워드와 매치되므로 유지되어야 함)
        _heading("문의처", order=24),
        _block("운영사무국 02-1234-5678 / contact@example.org", order=25),
        # heading 없는 footer 잔재가 마지막 섹션(문의처, KEEP)에 이어붙는 경우 -> 블록 단위로 걸러져야 함
        _block("Copyright ⓒ 청년창업진흥원 all rights reserved", order=26),
    ]
    return _page(blocks)


def test_contest_page_keeps_core_sections_and_removes_noise():
    page = _build_contest_page()
    result = clean_page_content(page)

    _assert_partition_invariants(page, result)

    kept_texts = [b.content for b in result.cleaned_blocks]
    kept_join = "\n".join(kept_texts)

    # 핵심 정보는 유지
    assert "2026년도 청년 창업 아이디어 공모전" in kept_join
    assert "주최: 중소벤처기업부" in kept_join
    assert "2026.08.01 ~ 2026.08.31" in kept_join
    assert "만 19~39세" in kept_join
    assert "지속가능한 지역 문제 해결형" in kept_join
    assert "이메일 접수" in kept_join
    assert "창의성 40%" in kept_join
    assert "대상 1팀 상금 500만원" in kept_join
    assert "운영사무국 02-1234-5678" in kept_join  # 문의처는 전화번호가 있어도 유지

    # 노이즈는 제거 (heading이 REMOVE 매치이므로 본문에 접수기간/참가자격이 있어도 통째로 제거)
    assert "함께 보면 좋은 공모전" not in kept_join
    assert "2026 대학생 아이디어 공모전" not in kept_join
    assert "전국 사진 공모전" not in kept_join
    # 상단 메뉴 제거
    assert "대외활동" not in kept_join
    assert "로그인" not in kept_join
    # KEEP 섹션 내부에 섞인 상용구는 블록 단위로 제거
    assert "이용약관" not in kept_join
    assert "Copyright" not in kept_join

    removed_reasons = {rb.reason for rb in result.removed_blocks}
    assert RemovalReason.RECOMMENDED_CONTENT in removed_reasons
    assert RemovalReason.COMPANY_INFO_FOOTER in removed_reasons
    assert not result.fallback_used


# ---------------------------------------------------------------------------
# 오탐 방지: 표면적으로 같은 신호(전화번호)라도 문맥에 따라 다르게 처리되어야 함
# ---------------------------------------------------------------------------

def test_phone_number_alone_without_contact_heading_is_removed_as_footer():
    blocks = [
        _heading("참가자격", order=0),
        _block("대학생 및 일반인 누구나 참가 가능", order=1),
        _block("고객센터 02-0000-0000 사업자등록번호 111-11-11111", order=2),  # heading 없이 footer성 블록만 존재
    ]
    page = _page(blocks)
    result = clean_page_content(page)

    _assert_partition_invariants(page, result)
    kept_join = "\n".join(b.content for b in result.cleaned_blocks)
    assert "대학생 및 일반인" in kept_join
    assert "고객센터 02-0000-0000" not in kept_join


def test_short_intro_paragraph_at_top_is_not_removed_as_menu():
    """최상단의 짧은 문장 한 줄은 메뉴형 나열 조건(다수의 짧은 항목)을 만족하지 않으므로 유지되어야 함"""
    blocks = [
        _block("이번 공모전은 대학생을 위한 특별 이벤트입니다.", order=0),  # 12자 초과, 단일 블록
        _heading("참가자격", order=1),
        _block("전국 대학생 누구나", order=2),
    ]
    page = _page(blocks)
    result = clean_page_content(page)

    kept_join = "\n".join(b.content for b in result.cleaned_blocks)
    assert "특별 이벤트" in kept_join


def test_menu_like_preamble_is_removed():
    blocks = [
        _block("홈", order=0),
        _block("공모전", order=1),
        _block("대외활동", order=2),
        _block("마이페이지", order=3),
        _heading("참가자격", order=4),
        _block("전국 대학생 누구나", order=5),
    ]
    page = _page(blocks)
    result = clean_page_content(page)

    kept_join = "\n".join(b.content for b in result.cleaned_blocks)
    assert not any(b.content == "홈" for b in result.cleaned_blocks)
    assert not any(b.content == "마이페이지" for b in result.cleaned_blocks)
    assert "전국 대학생 누구나" in kept_join


def _build_thinkyou_like_page() -> WebPageContent:
    """
    실제 thinkyou.co.kr 공모전 페이지(https://thinkyou.co.kr/contest/64591) 수동 검증에서
    확인된 상단 메뉴 블록 0~4를 축약 없이 그대로 재현한 회귀 fixture.
    (원본 33블록 / 0~4 상단메뉴 / 5~17 핵심내용 / 18~32 추천콘텐츠+footer)
    """
    blocks = [
        # 0~4: 실제 사이트에서 확인된 상단 메뉴 블록 (그대로 재현, 축약하지 않음)
        _block(
            "공모전아이디어/마케팅광고/디자인/웹툰영상/UCC/사진...대외활동서포터즈봉사활동체험단..."
            "씽유PICK이주의 주목할 공모전...이벤트",
            block_type=WebBlockType.LIST, order=0,
        ),
        _block(
            "아이디어/마케팅\n광고/디자인/웹툰\n영상/UCC/사진\n학술/논문\n문학예술\nIT/SW",
            block_type=WebBlockType.LIST, order=1,
        ),
        _block(
            "서포터즈\n봉사활동\n체험단\n강연/취업\n교육\n기타",
            block_type=WebBlockType.LIST, order=2,
        ),
        _block(
            "이주의 주목할 공모전\n씽유추천! 대외활동\n정보터\n수상작 갤러리\n시상식 갤러리",
            order=3,
        ),
        _block(
            "배너광고 안내\n공모전 대행안내\n공모전 무료 등록\n자주묻는질문",
            order=4,
        ),
        # 5~17: 핵심 내용 (13블록)
        _heading("2026 씽유 온라인 공모전", order=5, level=1),
        _block("본 공모전은 대학생을 위한 창업 아이디어 공모전입니다.", order=6),
        _heading("공모요강", order=7),
        _block("자세한 내용은 아래와 같습니다.", order=8),
        _heading("접수기간", order=9),
        _block("2026.09.01 ~ 2026.09.30", order=10),
        _heading("참가자격", order=11),
        _block("전국 대학생 및 대학원생", order=12),
        _heading("공모주제", order=13),
        _block("AI 활용 창업 아이디어", order=14),
        _heading("제출방법", order=15),
        _block("이메일 제출 (contest@thinkyou.co.kr)", order=16),
        _heading("시상내역", order=17),
        # 18~32: 추천 콘텐츠 + footer (15블록, 전부 제거 대상)
        _heading("함께 보면 좋은 공모전", order=18),
        _block("[2026 대학생 창업경진대회] 접수기간: 2026.10.01~2026.10.31", order=19),
        _block("[전국 사진 공모전] 참가자격: 전국민 누구나", order=20),
        _heading("이런 공모전은 어때요", order=21),
        _block("[봉사활동 공모전] 참가자격: 대학생", order=22),
        _heading("최신 공모전", order=23),
        _block("[디자인 공모전] 제출방법: 이메일 접수", order=24),
        _heading("뉴스레터 구독", order=25),
        _block("매주 새로운 공모전 소식을 받아보세요", order=26),
        _heading("회사소개", order=27),
        _block("㈜씽유 대표: 홍길동 사업자등록번호: 123-45-67890", order=28),
        _block("통신판매업신고 제2026-서울강남-00000호", order=29),
        _heading("이용약관", order=30),
        _block("이용약관 전문 내용입니다.", order=31),
        _block("Copyright ⓒ 씽유 all rights reserved", order=32),
    ]
    return _page(blocks, url="https://thinkyou.co.kr/contest/64591")


def test_thinkyou_real_page_removes_top_menu_preamble_and_recommended_footer():
    """
    실제 thinkyou.co.kr 페이지 수동 검증에서 재발이 확인된 회귀 케이스.
    블록 0~4(상단 메뉴)가 "시상"(KEEP 키워드) 오탐으로 인해 preamble 가드에 막혀
    UNKNOWN->KEEP 되어버리던 문제를 고정한다.
    """
    page = _build_thinkyou_like_page()
    assert len(page.blocks) == 33

    result = clean_page_content(page)
    _assert_partition_invariants(page, result)

    kept_orders = [b.order for b in result.cleaned_blocks]
    removed_orders = {rb.block.order for rb in result.removed_blocks}

    assert set(range(0, 5)).issubset(removed_orders)     # 0~4 상단 메뉴 -> 제거
    assert set(range(5, 18)) == set(kept_orders)          # 5~17 핵심 내용 -> 유지
    assert set(range(18, 33)).issubset(removed_orders)    # 18~32 추천/footer -> 제거

    assert result.cleaned_block_count == 13
    assert result.fallback_used is False

    menu_removed = [rb for rb in result.removed_blocks if rb.block.order in range(0, 5)]
    assert len(menu_removed) == 5
    assert all(rb.reason == RemovalReason.UNCLASSIFIED_STRUCTURAL_NOISE for rb in menu_removed)

    assert not any("heading 없음" in w for w in result.warnings)
    assert not any("공모요강" in w for w in result.warnings)


def test_unknown_heading_is_kept_with_warning():
    """첫 heading(제목)은 title 휴리스틱으로 KEEP되므로, UNKNOWN 경로를 보려면 두 번째 이후 heading이어야 함"""
    blocks = [
        _heading("2026년도 공모전", order=0),  # 첫 heading -> 제목으로 간주되어 KEEP
        _block("공모전 소개 문구입니다.", order=1),
        _heading("TIP", order=2),  # 키워드 사전 어디에도 없는 낯선 heading
        _block("공모전에 도전할 때 참고하면 좋은 팁입니다.", order=3),
    ]
    page = _page(blocks)
    result = clean_page_content(page)

    kept_join = "\n".join(b.content for b in result.cleaned_blocks)
    assert "참고하면 좋은 팁" in kept_join
    assert any("규칙으로 분류되지 않아" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# 정확 중복 제거
# ---------------------------------------------------------------------------

def test_exact_duplicate_block_is_removed_keeping_first_occurrence():
    blocks = [
        _heading("문의처", order=0),
        _block("운영사무국 02-1234-5678", order=1),
        _heading("유의사항", order=2),
        _block("운영사무국 02-1234-5678", order=3),  # 동일 내용 반복
    ]
    page = _page(blocks)
    result = clean_page_content(page)

    _assert_partition_invariants(page, result)
    contact_occurrences = [b for b in result.cleaned_blocks if b.content == "운영사무국 02-1234-5678"]
    assert len(contact_occurrences) == 1
    assert contact_occurrences[0].order == 1  # 첫 등장(문의처 섹션)이 유지됨

    dup_removed = [rb for rb in result.removed_blocks if rb.reason == RemovalReason.DUPLICATE]
    assert len(dup_removed) == 1
    assert dup_removed[0].block.order == 3


# ---------------------------------------------------------------------------
# 경계 케이스: 빈 페이지 / 전부 제거 대상 / fallback
# ---------------------------------------------------------------------------

def test_empty_page_returns_empty_result_without_error():
    page = _page([])
    result = clean_page_content(page)

    assert result.original_block_count == 0
    assert result.cleaned_block_count == 0
    assert result.cleaned_blocks == []
    assert result.removed_blocks == []
    assert result.fallback_used is False
    assert result.retention_ratio == 0.0


def test_all_blocks_classified_as_noise_triggers_fallback():
    long_filler = "광고입니다. " * 40  # 200자 이상으로 만들어 fallback 임계값(원문 길이) 조건 충족
    blocks = [
        _heading("광고", order=0),
        _block(long_filler, order=1),
        _heading("로그인", order=2),
        _block("아이디 찾기 / 비밀번호 찾기", order=3),
    ]
    page = _page(blocks)
    assert page.text_length >= 200

    result = clean_page_content(page)

    assert result.fallback_used is True
    assert result.cleaned_block_count == result.original_block_count
    assert result.removed_blocks == []
    assert result.retention_ratio == 1.0
    assert any("안전 모드" in w or "fallback" in w.lower() for w in result.warnings)
    _assert_partition_invariants(page, result)


def test_fallback_not_triggered_when_removed_content_is_trivial():
    """제거되는 노이즈가 소량이면(원문이 짧으면) fallback이 발동하지 않아야 함"""
    blocks = [
        _heading("참가자격", order=0),
        _block("전국 누구나 참가 가능", order=1),
        _block("로그인", order=2),  # heading 없이 딸려있는 아주 짧은 노이즈 한 줄(메뉴형 아님, 단일 블록)
    ]
    page = _page(blocks)
    result = clean_page_content(page)

    assert result.fallback_used is False


# ---------------------------------------------------------------------------
# 결정성(동일 입력 -> 동일 결과) 및 원본 불변성
# ---------------------------------------------------------------------------

def test_same_input_produces_same_output():
    page = _build_contest_page()
    result1 = clean_page_content(page)
    result2 = clean_page_content(page)

    assert result1.model_dump(exclude={"cleaned_blocks", "removed_blocks"}) == result2.model_dump(exclude={"cleaned_blocks", "removed_blocks"})
    assert [b.content for b in result1.cleaned_blocks] == [b.content for b in result2.cleaned_blocks]
    assert [rb.block.content for rb in result1.removed_blocks] == [rb.block.content for rb in result2.removed_blocks]


def test_original_page_and_blocks_are_not_mutated():
    page = _build_contest_page()
    snapshot = copy.deepcopy(page)

    clean_page_content(page)

    assert page.model_dump() == snapshot.model_dump()
    for original, after in zip(snapshot.blocks, page.blocks):
        assert original.content == after.content
        assert original.metadata == after.metadata
        assert original.order == after.order
        assert original.block_type == after.block_type
