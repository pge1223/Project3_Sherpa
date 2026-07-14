"""
수동 검증 스크립트: 첨부파일 탐색 여부 확인
=============================================
운영 코드는 전혀 수정하지 않고, 기존 ai.rag.loaders.load_from_url()만 호출해
지정한 URL에서 첨부파일이 정상적으로 탐색/파싱되는지 눈으로 확인하기 위한 스크립트.

- 다운로드된 첨부파일은 load_from_url() 내부에서 임시 디렉토리(tempfile.TemporaryDirectory)에
  받았다가 파싱 직후 자동 삭제되므로, 이 스크립트는 별도의 파일 저장/정리 로직을 갖지 않는다.
- API 키/환경변수를 사용하지 않는다 (load_from_url()도 사용하지 않음).
"""

import sys

from ai.rag.loaders import load_from_url

# Windows 콘솔(cp949)에서 페이지 title 등에 섞인 BOM/특수문자 출력 시 UnicodeEncodeError로
# 스크립트가 죽는 것을 막기 위한 안전장치 (loaders 동작과는 무관, 출력 표시 전용)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TEST_URL = "https://thinkyou.co.kr/contest/64647"
ATTACHMENT_MENTION_KEYWORDS = ("첨부파일", "다운로드")


def _print_section(title: str) -> None:
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def main() -> None:
    result = load_from_url(TEST_URL)

    # 1) 기본 정보
    _print_section("1. 기본 정보")
    print("origin_url:", result.origin_url)
    print("fetch_target_type:", result.fetch_target_type)
    print("page title:", result.page_content.title if result.page_content else None)
    print("warnings:")
    for warning in result.warnings:
        print(" -", warning)

    # 2) 정상 파싱된 첨부파일
    _print_section("2. 정상 파싱된 첨부파일")
    print("attachments 개수:", len(result.attachments))
    for attachment in result.attachments:
        extraction = attachment.extraction
        print("-" * 60)
        print("attachment_url:", attachment.attachment_url)
        print("file_name:", attachment.file_name)
        print("source_page_url:", attachment.source_page_url)
        print("extraction.file_type:", getattr(extraction, "file_type", "N/A"))
        print("extraction.block_count:", getattr(extraction, "block_count", "N/A"))
        print("extraction.is_scanned_pdf:", getattr(extraction, "is_scanned_pdf", "N/A"))
        print("extraction.requires_ocr:", getattr(extraction, "requires_ocr", "N/A"))
        print("extraction.warnings:", getattr(extraction, "warnings", []))

    # 3) 미지원 첨부파일
    _print_section("3. 미지원 첨부파일")
    print("unsupported_attachments 개수:", len(result.unsupported_attachments))
    for unsupported in result.unsupported_attachments:
        print("-" * 60)
        print("url:", getattr(unsupported, "url", "N/A"))
        print("file_name:", getattr(unsupported, "file_name", "N/A"))
        print("reason:", getattr(unsupported, "reason", "N/A"))

    # 4) 실패한 첨부파일
    _print_section("4. 실패한 첨부파일")
    print("failed_attachments 개수:", len(result.failed_attachments))
    for failed in result.failed_attachments:
        print("-" * 60)
        print("url:", getattr(failed, "url", "N/A"))
        print("file_name:", getattr(failed, "file_name", "N/A"))
        print("error_code:", getattr(failed, "error_code", "N/A"))
        print("message:", getattr(failed, "message", "N/A"))

    # 5) 최종 판정
    _print_section("5. 최종 판정")
    page_mentions_attachment = False
    if result.page_content is not None:
        page_text = getattr(result.page_content, "text", "") or ""
        page_mentions_attachment = any(keyword in page_text for keyword in ATTACHMENT_MENTION_KEYWORDS)

    if len(result.attachments) >= 1:
        verdict = "지원 형식 첨부파일 탐색 및 파싱 성공"
    elif len(result.unsupported_attachments) >= 1:
        verdict = "첨부파일은 탐색했지만 HWP/HWPX 등 미지원 형식"
    elif len(result.failed_attachments) >= 1:
        verdict = "첨부 링크는 탐색했지만 다운로드 또는 형식 검증/파싱 실패"
    elif page_mentions_attachment:
        verdict = "페이지에는 첨부파일 표시가 있으나 링크 탐색 결과가 없어 추가 확인 필요"
    else:
        verdict = "첨부파일 관련 표시나 탐색 결과가 없음"

    print(verdict)


if __name__ == "__main__":
    main()
