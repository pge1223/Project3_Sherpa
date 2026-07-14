from ai.rag.loaders import load_from_url


def main():
    url = "https://thinkyou.co.kr/contest/64591"

    result = load_from_url(url)

    print("\n=== 기본 정보 ===")
    print("URL 종류:", result.fetch_target_type)
    print("원본 URL:", result.origin_url)

    if result.page_content:
        print("페이지 제목:", result.page_content.title)
        print("본문 길이:", result.page_content.text_length)
        print("JS 페이지 의심:", result.page_content.is_js_rendered_suspected)

        print("\n=== 웹페이지 블록 ===")
        for block in result.page_content.blocks:
            print("-" * 60)
            print("종류:", block.block_type)
            print("순서:", block.order)
            print("내용:", block.content)

    print("\n=== 첨부파일 ===")
    for attachment in result.attachments:
        print(
            attachment.file_name,
            attachment.extraction.file_type,
            attachment.extraction.block_count,
        )

    print("\n미지원 파일:", result.unsupported_attachments)
    print("실패 파일:", result.failed_attachments)
    print("경고:", result.warnings)


if __name__ == "__main__":
    main()