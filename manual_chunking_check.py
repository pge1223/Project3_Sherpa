from ai.rag.loaders import load_from_url
from ai.rag.preprocessing import clean_page_content
from ai.rag.chunking import (
    chunk_document,
    ChunkSourceContext,
    SourceType,
)

url = "https://thinkyou.co.kr/contest/64647"

url_result = load_from_url(url)

if not url_result.page_content:
    raise RuntimeError("웹페이지 본문이 없습니다.")

cleaned = clean_page_content(url_result.page_content)

context = ChunkSourceContext(
    document_id="manual_web_doc_001",
    source_type=SourceType.URL_WEBPAGE,
    source_url=url_result.origin_url,
    source_page_url=url_result.origin_url,
    document_title=url_result.page_content.title,
)

chunking_result = chunk_document(cleaned, context)

print("청크 수:", chunking_result.chunk_count)
print("경고:", chunking_result.warnings)

for chunk in chunking_result.chunks:
    print("-" * 70)
    print("ID:", chunk.chunk_id)
    print("순서:", chunk.chunk_index)
    print("종류:", chunk.content_kind)
    print("위치:", chunk.location_type, chunk.location_number)
    print("섹션:", chunk.section_title)
    print("글자 수:", chunk.char_count)
    print("원본 order:", chunk.source_block_orders)
    print("색인 여부:", chunk.indexable)
    print("내용:", chunk.content)