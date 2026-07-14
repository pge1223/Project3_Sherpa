"""
Manual OCR Check Script
=======================
test2.pdf 파일을 OCR 처리하여 결과를 확인합니다.
"""
import sys
# Windows에서 UTF-8 출력 강제 설정
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from collections import Counter
from pathlib import Path

from ai.rag.parsers import PDFParser
from ai.rag.parsers.easyocr_engine import EasyOCR


def main():
    # test2.pdf 경로 (프로젝트 루트 또는 fixtures 폴더)
    possible_paths = [
        Path(__file__).parent / "test2.pdf",
        Path(__file__).parent / "ai" / "rag" / "tests" / "fixtures" / "test2.pdf",
    ]

    pdf_path = None
    for p in possible_paths:
        if p.exists():
            pdf_path = p
            break

    if pdf_path is None:
        print(f"오류: test2.pdf 파일을 찾을 수 없습니다.")
        print(f"검색 경로: {[str(p) for p in possible_paths]}")
        return

    print(f"OCR 처리 시작: {pdf_path}")

    # EasyOCR 엔진 초기화
    ocr = EasyOCR(languages=["ko", "en"], gpu=False)
    if not ocr.is_available():
        print("경고: EasyOCR을 사용할 수 없습니다. OCR 없이 파싱합니다.")
        ocr = None

    # PDFParser로 OCR 포함 파싱
    parser = PDFParser(str(pdf_path), ocr_engine=ocr)
    result = parser.parse()

    # 전체 결과 JSON 출력
    print("\n" + "=" * 60)
    print("문서 전체 결과 (JSON)")
    print("=" * 60)
    print(result.model_dump_json(indent=2))

    # 주요 정보 출력
    print("\n" + "=" * 60)
    print("추출 결과 요약")
    print("=" * 60)
    print(f"is_scanned_pdf: {result.is_scanned_pdf}")
    print(f"requires_ocr: {result.requires_ocr}")
    print(f"페이지 수: {result.page_count}")
    print(f"총 블록 수: {result.block_count}")
    print(f"파일 크기: {result.file_size:,} bytes")

    # 경고 출력
    if result.warnings:
        print("\n--- 경고 ---")
        for warning in result.warnings:
            print(f"  [!] {warning}")

    # 블록별 상세 정보
    print("\n" + "=" * 60)
    print("블록별 상세 정보")
    print("=" * 60)

    for i, block in enumerate(result.blocks):
        print(f"\n[블록 {i + 1}]")
        print(f"  location_type: {block.location_type}")
        print(f"  location_number: {block.location_number}")
        print(f"  block_type: {block.block_type}")
        print(f"  content: {block.content[:200]}{'...' if len(block.content) > 200 else ''}")
        print(f"  order: {block.order}")
        print(f"  block_id: {block.block_id}")

        # OCR 메타데이터
        if block.metadata.get("ocr_performed"):
            print(f"  [OCR 정보]")
            print(f"    ocr_engine: {block.metadata.get('ocr_engine', 'N/A')}")
            print(f"    ocr_confidence: {block.metadata.get('ocr_confidence', 'N/A')}")

    # location_number별 블록 수统计
    print("\n" + "=" * 60)
    print("페이지별 블록 분포")
    print("=" * 60)

    from collections import Counter
    page_counts = Counter(b.location_number for b in result.blocks)
    for page_num in sorted(page_counts.keys()):
        print(f"  페이지 {page_num}: {page_counts[page_num]}개 블록")


if __name__ == "__main__":
    main()