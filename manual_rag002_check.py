"""
RAG-002 수동 검증 스크립트
============================
실제 공모전 URL을 대상으로 load_from_url() -> clean_page_content() -> chunk_document()
-> RAGIndexingService.index_chunking_result() -> search() 전체 파이프라인을 눈으로 확인한다.

운영 코드/테스트 코드는 이 스크립트에 의존하지 않는다 (일회성 수동 검증 전용).

실행 (review-board conda env, PowerShell):
    & "C:\\Anaconda3\\envs\\review-board\\python.exe" manual_rag002_check.py
"""

import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from ai.rag.loaders.url_loader import load_from_url
from ai.rag.preprocessing.html_cleaner import clean_page_content
from ai.rag.chunking import chunk_document, ChunkSourceContext, SourceType
from ai.rag.domain import IndexingContext
from ai.rag.embedding.kure_embedder import KUREEmbedder
from ai.rag.retrieval.chroma_store import ChromaVectorStore, create_persistent_client
from ai.rag.retrieval.service import RAGIndexingService

TEST_URL = "https://thinkyou.co.kr/contest/64647"
PROJECT_ID = "manual-check-project"
DOCUMENT_ID = "manual-check-doc-1"
QUESTIONS = [
    "접수기간은 언제인가요?",
    "AI 도구를 활용할 수 있나요?",
    "숏폼 출품 규격은 어떻게 되나요?",
    "문의처 전화번호는 무엇인가요?",
]


def main() -> None:
    print(f"[1] load_from_url({TEST_URL})")
    url_result = load_from_url(TEST_URL)
    if url_result.page_content is None:
        print("  page_content가 없습니다 (DIRECT_FILE이거나 실패). 중단합니다.")
        return
    print(f"  title={url_result.page_content.title!r}, blocks={len(url_result.page_content.blocks)}, warnings={url_result.warnings}")

    print("[2] clean_page_content()")
    cleaned = clean_page_content(url_result.page_content)
    print(f"  cleaned_block_count={cleaned.cleaned_block_count}, retention_ratio={cleaned.retention_ratio:.2f}, fallback_used={cleaned.fallback_used}")

    print("[3] chunk_document()")
    context = ChunkSourceContext(
        document_id=DOCUMENT_ID,
        source_type=SourceType.URL_WEBPAGE,
        source_url=TEST_URL,
        document_title=url_result.page_content.title,
    )
    chunking_result = chunk_document(cleaned, context)
    indexable_count = sum(1 for c in chunking_result.chunks if c.indexable)
    print(f"  chunk_count={chunking_result.chunk_count}, indexable={indexable_count}, warnings={len(chunking_result.warnings)}")
    for w in chunking_result.warnings:
        print(f"    - {w}")

    tmp_dir = tempfile.mkdtemp(prefix="manual_rag002_chroma_")
    try:
        print(f"[4] index_chunking_result() (chroma persist dir: {tmp_dir})")
        embedder = KUREEmbedder()
        client = create_persistent_client(path=tmp_dir)
        store = ChromaVectorStore(
            client=client,
            collection_name="project_documents_kure_v1",
            embedding_model=embedder.model_name,
            embedding_dimension=embedder.embedding_dimension,
            embedding_version="embedding_v1",
        )
        service = RAGIndexingService(embedder, store)

        indexing_context = IndexingContext(
            project_id=PROJECT_ID,
            document_id=DOCUMENT_ID,
            document_title=url_result.page_content.title,
        )
        indexing_result = service.index_chunking_result(chunking_result, indexing_context)
        print(f"  embedded={indexing_result.embedded_count}, upserted={indexing_result.upserted_count}, "
              f"stored={indexing_result.stored_record_count}, skipped={indexing_result.skipped_count}, "
              f"failed={indexing_result.failed_count}, status={indexing_result.status.value}")
        assert indexing_result.embedded_count == indexing_count_check(chunking_result), \
            "청크 수와 임베딩 수가 예상과 다릅니다"

        print("[4b] 같은 문서 재색인 (중복 없음 확인)")
        reindex_result = service.index_chunking_result(chunking_result, indexing_context)
        print(f"  재색인 후 stored={reindex_result.stored_record_count} (변화 없어야 함), "
              f"deleted_stale={reindex_result.deleted_stale_count} (0이어야 함)")

        print("[5] search() 질문별 Top-3 검색")
        for question in QUESTIONS:
            print(f"\n  Q: {question}")
            results = service.search(question, project_id=PROJECT_ID, top_k=3)
            if not results:
                print("    (검색 결과 없음)")
            for r in results:
                preview = r.content[:80].replace("\n", " ")
                print(f"    - score={r.score}, section_title={r.metadata.get('section_title')!r}, "
                      f"location={r.metadata.get('location_type')}/{r.metadata.get('location_number')}")
                print(f"      content: {preview}...")

        print("\n[6] project_id 필터 확인 (다른 project_id로는 검색 안 됨)")
        other_project_results = service.search(QUESTIONS[0], project_id="other-project-should-be-empty", top_k=3)
        print(f"  다른 project_id 검색 결과 수: {len(other_project_results)} (0이어야 함)")

        print("\n[7] 저장 폴더 재오픈 후 검색 가능 확인")
        client2 = create_persistent_client(path=tmp_dir)
        store2 = ChromaVectorStore(
            client=client2,
            collection_name="project_documents_kure_v1",
            embedding_model=embedder.model_name,
            embedding_dimension=embedder.embedding_dimension,
            embedding_version="embedding_v1",
        )
        service2 = RAGIndexingService(embedder, store2)
        reopened_results = service2.search(QUESTIONS[0], project_id=PROJECT_ID, top_k=1)
        print(f"  재오픈 후 검색 결과 수: {len(reopened_results)} (1개 이상이어야 함)")

        print("\n=== 수동 검증 완료 ===")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def indexing_count_check(chunking_result) -> int:
    return sum(1 for c in chunking_result.chunks if c.indexable and c.content.strip())


if __name__ == "__main__":
    main()
