from ai.rag.loaders import load_from_url
from ai.rag.preprocessing import clean_page_content


def main():
    url = "https://thinkyou.co.kr/contest/64647"

    result = load_from_url(url)

    if not result.page_content:
        print("웹페이지 본문이 없습니다.")
        return

    cleaned = clean_page_content(result.page_content)

    print("\n=== 정제 결과 요약 ===")
    print("원본 블록 수:", cleaned.original_block_count)
    print("정제 블록 수:", cleaned.cleaned_block_count)
    print("원본 글자 수:", cleaned.original_text_length)
    print("정제 글자 수:", cleaned.cleaned_text_length)
    print("유지 비율:", cleaned.retention_ratio)
    print("Fallback 사용:", cleaned.fallback_used)
    print("경고:", cleaned.warnings)

    print("\n=== 유지된 블록 ===")
    for block in cleaned.cleaned_blocks:
        print("-" * 60)
        print("순서:", block.order)
        print("종류:", block.block_type)
        print("내용:", block.content)

    print("\n=== 제거된 블록 ===")
    for removed in cleaned.removed_blocks:
        print("-" * 60)
        print("순서:", removed.block.order)
        print("제거 이유:", removed.reason)
        print("상세 근거:", removed.detail)
        print("내용:", removed.block.content)


if __name__ == "__main__":
    main()