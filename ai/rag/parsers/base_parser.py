"""
Base Parser Abstract Class
=========================
"""

import hashlib
from abc import ABC, abstractmethod
from pathlib import Path

from ai.rag.parsers.schemas import (
    FileType,
    LocationType,
    BlockType,
    DocumentBlock,
    DocumentExtractionResult,
)


class BaseParser(ABC):
    """
    문서 파서 기본 클래스

    모든 파서는 이 클래스를 상속받아 구현하며,
    공통 로직(문서 ID 생성, 결과 포장 등)을 제공
    """

    def __init__(self, file_path: str | Path):
        self.file_path = Path(file_path)
        self._validate_file()

    def _validate_file(self) -> None:
        """파일 존재 및 기본 검증"""
        if not self.file_path.exists():
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {self.file_path}")

    @abstractmethod
    def get_file_type(self) -> FileType:
        """파일 형식 반환 (서브클래스에서 구현)"""
        pass

    @abstractmethod
    def get_page_count(self) -> int | None:
        """페이지/슬라이드 수 반환 (서브클래스에서 구현)"""
        pass

    @abstractmethod
    def parse(self) -> DocumentExtractionResult:
        """문서 파싱 실행 (서브클래스에서 구현)"""
        pass

    def generate_document_id(self, file_path: Path) -> str:
        """
        문서 ID 생성 (파일명 기반 deterministic hash)

        동일한 파일명에 대해 항상 동일한 ID 생성
        """
        file_name = file_path.name.encode("utf-8")
        hash_obj = hashlib.sha256(file_name)
        return f"doc_{hash_obj.hexdigest()[:16]}"

    def generate_block_id(
        self,
        document_id: str,
        location_type: LocationType,
        location_number: int | None,
        order: int,
    ) -> str:
        """
        블록 ID 생성 (deterministic)

        document_id, location, order가 동일하면 항상 동일한 ID 반환
        """
        loc_num = location_number if location_number is not None else 0
        raw = f"{document_id}:{location_type.value}:{loc_num}:{order}"
        hash_obj = hashlib.sha256(raw.encode("utf-8"))
        return f"blk_{hash_obj.hexdigest()[:12]}"

    def create_result(
        self,
        file_size: int,
        page_count: int | None,
        blocks: list[DocumentBlock],
        is_scanned_pdf: bool = False,
        requires_ocr: bool = False,
        warnings: list[str] | None = None,
    ) -> DocumentExtractionResult:
        """파싱 결과를 공통 형식으로 포장"""
        return DocumentExtractionResult(
            document_id=self.generate_document_id(self.file_path),
            file_name=self.file_path.name,
            file_type=self.get_file_type(),
            file_size=file_size,
            page_count=page_count,
            block_count=len(blocks),
            blocks=blocks,
            is_scanned_pdf=is_scanned_pdf,
            requires_ocr=requires_ocr,
            warnings=warnings or [],
        )
