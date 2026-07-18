"""
HWPX RAG 품질 검증 스크립트 (수동 실행 전용, pytest 대상 아님)
================================================================================
실제 사용자 파일(HWPX)을 텍스트 정규화/section 메타데이터/검색 결과 내 중복 제거
적용 전/후로 비교한다. 임시 디렉터리(TemporaryDirectory, 프로세스 종료 시 자동 정리)만
쓰며 운영 Chroma 데이터는 전혀 건드리지 않는다.

실행 (repo 루트에서):
    python scripts/verify_klawyer_rag_quality.py "<hwpx 경로>"
    python scripts/verify_klawyer_rag_quality.py --help   # KURE/LibreOffice 로드 없이 즉시 종료

종료 코드:
    0 = 검증 완료 (아래 모든 단계 성공)
    1 = 입력 파일을 찾을 수 없음
    2 = HWPX -> PDF 변환 실패 (LibreOffice 미설치/미탐색 등)
    3 = 파싱/청킹 실패
    4 = 임베딩/Chroma 색인/검색 실패
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# repo 루트를 sys.path에 넣어 `python scripts/verify_klawyer_rag_quality.py`를 별도
# PYTHONPATH 설정 없이 바로 실행할 수 있게 한다 (ai.rag.* import는 이 아래, argparse 이후에만 함 —
# --help가 KURE/LibreOffice를 로드하지 않고 즉시 끝나야 하므로 무거운 import를 여기 두지 않는다).
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

PROJECT_ID = "6a5a476b16d5398c7c06d53c"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="HWPX 문서로 RAG 청킹/section/검색 결과 중복 제거 개선을 before/after로 검증한다.",
    )
    parser.add_argument("hwpx_path", type=Path, help="검증할 HWPX 파일 경로 (필수)")
    return parser.parse_args(argv)


def _stats(chunks) -> dict:
    total = len(chunks)
    with_section = sum(1 for c in chunks if c.section_title)
    return {
        "total_chunks": total,
        "with_section": with_section,
        "with_section_ratio": round(with_section / total, 3) if total else 0.0,
        "null_section": total - with_section,
    }


def _duplicate_rate(contents: list[str]) -> float:
    normalized = [re.sub(r"\s+", " ", c).strip().lower() for c in contents]
    total = len(normalized)
    return round(1 - (len(set(normalized)) / total), 3) if total else 0.0


def _chunk_without_normalization(adapters_module, chunker_module, chunk_document, extraction, context):
    """정규화/whole-line heading 인식을 끈 "before" 재현: merge_wrapped_pdf_lines를 identity로,
    extract_whole_line_heading_title을 항상 None으로 되돌려 이번 작업 이전 동작을 그대로
    재현한다(프로덕션 코드는 건드리지 않고 이 스크립트 실행 중에만 patch)."""
    from unittest.mock import patch

    with patch.object(adapters_module, "merge_wrapped_pdf_lines", side_effect=lambda blocks: blocks), \
         patch.object(chunker_module, "extract_whole_line_heading_title", return_value=None):
        return chunk_document(extraction, context)


def run(hwpx_path: Path) -> int:
    if not hwpx_path.exists():
        print(f"[ERROR] 파일을 찾을 수 없습니다: {hwpx_path}")
        return 1

    # 무거운 import는 인자 검증을 통과한 뒤에만 수행한다.
    import tempfile

    from ai.rag.chunking import adapters as adapters_module
    from ai.rag.chunking import chunker as chunker_module
    from ai.rag.chunking.chunker import chunk_document
    from ai.rag.chunking.schemas import ChunkSourceContext, SourceType
    from ai.rag.converters.config import HwpConversionConfig
    from ai.rag.converters.exceptions import DocumentConversionError
    from ai.rag.converters.factory import convert_if_needed
    from ai.rag.domain.schemas import IndexingContext
    from ai.rag.embedding.kure_embedder import KUREEmbedder
    from ai.rag.parsers.unified_parser import extract_document
    from ai.rag.retrieval.chroma_store import ChromaVectorStore, create_persistent_client
    from ai.rag.retrieval.service import RAGIndexingService
    from ai.rag.role_retrieval.service import RoleAwareRetrievalService

    with tempfile.TemporaryDirectory(prefix="klawyer_verify_") as work_dir_str:
        work_dir = Path(work_dir_str)
        print(f"[INFO] 임시 작업 디렉터리(종료 시 자동 삭제): {work_dir}")

        print("[STEP] HWPX -> PDF 변환")
        try:
            conversion = convert_if_needed(hwpx_path, output_dir=work_dir, config=HwpConversionConfig(enabled=True))
        except DocumentConversionError as exc:
            print(f"[ERROR] HWPX -> PDF 변환 실패: {exc}")
            print(
                "[CHECK] 확인사항: (1) LibreOffice(soffice)가 설치되어 있는지, "
                "(2) PATH에 soffice가 없다면 HWP_CONVERTER_EXECUTABLE 환경변수로 실행 파일 경로를 "
                "지정했는지, (3) 파일이 손상되지 않았는지."
            )
            return 2

        parsed_path = hwpx_path if conversion is None else conversion.converted_path
        if conversion is not None and not conversion.success:
            print(f"[ERROR] HWPX -> PDF 변환 실패: {conversion.error_message}")
            print(
                "[CHECK] 확인사항: (1) LibreOffice(soffice)가 설치되어 있는지, "
                "(2) PATH에 soffice가 없다면 HWP_CONVERTER_EXECUTABLE 환경변수로 실행 파일 경로를 "
                "지정했는지, (3) 파일이 손상되지 않았는지."
            )
            return 2
        print(f"[INFO] 파싱 대상: {parsed_path}")

        print("[STEP] 파싱 + 청킹 (before/after)")
        try:
            extraction = extract_document(parsed_path)
            context = ChunkSourceContext(
                document_id="doc_klawyer_verify",
                source_type=SourceType.FILE_UPLOAD,
                source_filename=hwpx_path.name,
                file_type="pdf",
            )
            before_result = _chunk_without_normalization(
                adapters_module, chunker_module, chunk_document, extraction, context
            )
            after_result = chunk_document(extraction, context)
        except Exception as exc:  # 파싱/청킹은 다양한 예외(ParserError 하위 클래스 등)를 던질 수 있어 광범위하게 잡되 반드시 보고
            print(f"[ERROR] 파싱/청킹 실패: {exc!r}")
            return 3

        parsed_text_len = sum(len(b.content) for b in extraction.blocks)
        print(f"[INFO] block_count={extraction.block_count} parsed_text_len={parsed_text_len}")

        before_stats = _stats(before_result.chunks)
        after_stats = _stats(after_result.chunks)

        print("\n=== 1. 청크 통계 (before -> after) ===")
        for key in ("total_chunks", "with_section", "with_section_ratio", "null_section"):
            print(f"  {key}: {before_stats[key]} -> {after_stats[key]}")

        sample_before, sample_idx = None, None
        for i, c in enumerate(before_result.chunks):
            if "‧" in c.content or "\n" in c.content:
                sample_before, sample_idx = c.content, i
                break
        print("\n=== 2. 정규화 전/후 청크 내용 예시 ===")
        print(f"  [before] {sample_before!r}" if sample_before else "  (개행/‧ 포함 청크 없음)")
        if sample_idx is not None and sample_idx < len(after_result.chunks):
            print(f"  [after]  {after_result.chunks[sample_idx].content!r}")

        print("\n=== 3. section이 채워진 청크 예시 (after) ===")
        for c in after_result.chunks:
            if c.section_title:
                print(f"  section={c.section_title!r} content={c.content[:60]!r}...")

        print("\n[STEP] 임베딩 + 임시 Chroma 색인/검색 (KURE-v1, after 결과 기준)")
        try:
            _index_and_search(
                after_result=after_result,
                work_dir=work_dir,
                KUREEmbedder=KUREEmbedder,
                IndexingContext=IndexingContext,
                create_persistent_client=create_persistent_client,
                ChromaVectorStore=ChromaVectorStore,
                RAGIndexingService=RAGIndexingService,
                RoleAwareRetrievalService=RoleAwareRetrievalService,
            )
        except Exception as exc:
            print(f"[ERROR] 임베딩/Chroma 색인/검색 실패: {exc!r}")
            print("[NOTE] 위 1~3번 청킹 통계는 이 단계 실패와 무관하게 유효하지만, 검색 결과(4~7번)는 확인하지 못했습니다.")
            return 4
        # Windows에서 TemporaryDirectory가 chroma.sqlite3를 정리하기 전에 chromadb의 sqlite
        # 핸들이 반드시 해제되어 있어야 한다 — _index_and_search()가 함수 스코프를 벗어나며
        # client/store 참조가 사라지므로, 여기서 명시적으로 gc.collect()까지 걸어 확실히 한다.
        import gc

        gc.collect()

    print("\n[DONE] 검증 완료 (임시 디렉터리는 자동 삭제됨, 운영 Chroma 데이터는 건드리지 않음).")
    return 0


def _index_and_search(
    *,
    after_result,
    work_dir: Path,
    KUREEmbedder,
    IndexingContext,
    create_persistent_client,
    ChromaVectorStore,
    RAGIndexingService,
    RoleAwareRetrievalService,
) -> None:
    """임베딩 -> 임시 Chroma 색인 -> role-aware 검색까지 실행하고 결과를 출력한다.
    별도 함수로 분리해 client/store 등 chromadb 참조가 이 함수 반환과 동시에 사라지게 한다
    (run()의 TemporaryDirectory 정리 시점에 sqlite 파일이 아직 열려 있어 삭제에 실패하는
    Windows 문제를 피하기 위함)."""
    embedder = KUREEmbedder()
    indexing_context = IndexingContext(
        project_id=PROJECT_ID, document_id="doc_klawyer_verify", collection_name="verify_klawyer"
    )
    embedding_result = embedder.embed_chunking_result(after_result, indexing_context)
    print(f"[INFO] embedded_count={embedding_result.embedding_count} warnings={embedding_result.warnings}")

    client = create_persistent_client(path=str(work_dir / "chroma_tmp"))
    store = ChromaVectorStore(
        client=client,
        collection_name="verify_klawyer",
        embedding_model=embedder.model_name,
        embedding_dimension=embedder.embedding_dimension,
        embedding_version=embedding_result.embedding_version,
    )
    store.upsert_embedding_result(embedding_result, indexing_context)

    indexing_service = RAGIndexingService(vector_store=store, embedder=embedder)
    role_service = RoleAwareRetrievalService(retrieval_service=indexing_service)

    print("\n=== 4~7. persona/criterion별 검색 결과 (top_k=5) ===")
    for role_id, query in (
        ("policy", "정책 부합성"),
        ("technology", "시스템 요구사항 및 기능"),
        ("planning", "사업 필요성"),
    ):
        response = role_service.search_by_role(query=query, project_id=PROJECT_ID, role_id=role_id, top_k=5)
        texts = [r.content for r in response.results]
        dup_rate = _duplicate_rate(texts)
        print(f"\n  role_id={role_id} query={query!r} result_count={len(response.results)} 내부중복률={dup_rate}")
        for r in response.results:
            section = r.metadata.get("section_title")
            print(
                f"    score={r.final_score:.3f} semantic={r.semantic_score} section={section!r} "
                f"quote={r.content[:50]!r}..."
            )

    # chromadb는 PersistentClient를 내부 System 캐시에 보관해 sqlite 연결을 프로세스 전역으로
    # 유지한다 — 변수 참조를 없애고 gc.collect()만 해서는 Windows에서 파일 잠금이 풀리지
    # 않아 TemporaryDirectory 정리 시 PermissionError가 난다. close() + 캐시 무효화로 명시적으로 해제한다.
    client.close()
    type(client).clear_system_cache()


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    sys.exit(run(args.hwpx_path))


if __name__ == "__main__":
    main()
