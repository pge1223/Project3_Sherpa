"""
HWP/HWPX Parser (외부 한글 프로그램 설치 없이 파싱)
=================================================
- HWPX: ZIP+XML(OWPML) 구조이므로 표준 라이브러리(zipfile, xml.etree)만으로 텍스트 추출
- HWP(5.0, 구버전 바이너리): OLE Compound File 구조. olefile로 BodyText 스트림을 읽어
  레코드(HWPTAG_PARA_TEXT) 단위로 UTF-16LE 텍스트를 추출
"""

import re
import struct
import xml.etree.ElementTree as ET
import zipfile
import zlib

import olefile

from ai.rag.parsers.base_parser import BaseParser
from ai.rag.parsers.schemas import (
    FileType,
    LocationType,
    BlockType,
    DocumentBlock,
    DocumentExtractionResult,
)
from ai.rag.parsers.exceptions import CorruptedDocumentError, EmptyDocumentError

# HWPX 섹션 XML 경로 패턴: Contents/section0.xml, Contents/section1.xml, ...
_HWPX_SECTION_PATTERN = re.compile(r"^Contents/section\d+\.xml$")

# HWP 5.0 BodyText 레코드 태그: HWPTAG_PARA_TEXT = HWPTAG_BEGIN(0x10) + 51
_HWPTAG_PARA_TEXT = 67


def _local_tag(tag: str) -> str:
    """XML 네임스페이스 접두사를 제거하고 로컬 태그명만 반환 (예: '{ns}p' -> 'p')"""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _collect_paragraph_text(p_elem: ET.Element) -> str:
    """문단(p) 요소 하위의 모든 텍스트 런(t)을 순서대로 이어붙임"""
    parts = [t.text for t in p_elem.iter() if _local_tag(t.tag) == "t" and t.text]
    return "".join(parts)


def _table_to_text(tbl_elem: ET.Element) -> str:
    """표(tbl) 요소를 행(tr)/셀(tc) 단위로 순회해 탭/개행 구분 텍스트로 변환"""
    rows_text = []
    for tr in tbl_elem:
        if _local_tag(tr.tag) != "tr":
            continue
        cells_text = []
        for tc in tr:
            if _local_tag(tc.tag) != "tc":
                continue
            cell_paragraphs = [
                _collect_paragraph_text(p) for p in tc.iter() if _local_tag(p.tag) == "p"
            ]
            cells_text.append("\n".join(t for t in cell_paragraphs if t))
        rows_text.append("\t".join(cells_text))
    return "\n".join(rows_text)


class HWPXParser(BaseParser):
    """hwpx(ZIP+XML/OWPML) 파서 — 외부 라이브러리/한글 설치 없이 파이썬 표준 라이브러리만 사용"""

    def get_file_type(self) -> FileType:
        return FileType.HWPX

    def _list_sections(self, z: zipfile.ZipFile) -> list[str]:
        return sorted(
            (n for n in z.namelist() if _HWPX_SECTION_PATTERN.match(n)),
            key=lambda n: int(re.search(r"\d+", n).group()),
        )

    def get_page_count(self) -> int | None:
        try:
            with zipfile.ZipFile(self.file_path, "r") as z:
                return len(self._list_sections(z)) or None
        except (zipfile.BadZipFile, OSError):
            return None

    def _walk_section(
        self,
        elem: ET.Element,
        document_id: str,
        section_num: int,
        order_state: list[int],
        blocks: list[DocumentBlock],
    ) -> None:
        """섹션 XML을 재귀 순회하며 문단은 TEXT 블록, 표는 TABLE 블록으로 변환.
        표 내부 문단은 표 블록에 이미 포함되므로 별도 하위 순회를 하지 않는다."""
        tag = _local_tag(elem.tag)

        if tag == "p":
            text = _collect_paragraph_text(elem).strip()
            if text:
                order = order_state[0]
                blocks.append(DocumentBlock(
                    block_id=self.generate_block_id(
                        document_id, LocationType.DOCUMENT, section_num, order,
                    ),
                    block_type=BlockType.TEXT,
                    content=text,
                    location_type=LocationType.DOCUMENT,
                    location_number=section_num,
                    order=order,
                    metadata={},
                ))
                order_state[0] += 1
            return

        if tag == "tbl":
            text = _table_to_text(elem).strip()
            if text:
                order = order_state[0]
                blocks.append(DocumentBlock(
                    block_id=self.generate_block_id(
                        document_id, LocationType.DOCUMENT, section_num, order,
                    ),
                    block_type=BlockType.TABLE,
                    content=text,
                    location_type=LocationType.DOCUMENT,
                    location_number=section_num,
                    order=order,
                    metadata={},
                ))
                order_state[0] += 1
            return

        for child in elem:
            self._walk_section(child, document_id, section_num, order_state, blocks)

    def parse(self) -> DocumentExtractionResult:
        file_size = self.file_path.stat().st_size
        warnings: list[str] = []
        blocks: list[DocumentBlock] = []
        order_state = [0]

        try:
            z = zipfile.ZipFile(self.file_path, "r")
        except (zipfile.BadZipFile, OSError) as e:
            raise CorruptedDocumentError(f"HWPX 파일을 열 수 없습니다: {e}")

        with z:
            sections = self._list_sections(z)
            if not sections:
                raise CorruptedDocumentError(
                    "HWPX에서 본문(Contents/sectionN.xml)을 찾을 수 없습니다. 손상된 파일일 수 있습니다."
                )

            document_id = self.generate_document_id(self.file_path)

            for idx, section_name in enumerate(sections, start=1):
                try:
                    with z.open(section_name) as f:
                        root = ET.fromstring(f.read())
                except ET.ParseError as e:
                    warnings.append(f"섹션 {idx} 파싱 실패로 건너뜁니다: {e}")
                    continue

                self._walk_section(root, document_id, idx, order_state, blocks)

        if len(blocks) == 0:
            raise EmptyDocumentError(
                "HWPX에서 텍스트를 추출할 수 없습니다. 빈 문서이거나 손상된 파일일 수 있습니다."
            )

        return self.create_result(
            file_size=file_size,
            page_count=len(sections),
            blocks=blocks,
            warnings=warnings,
        )


def _clean_hwp_text(text: str) -> str:
    """HWP 레코드에서 나온 텍스트의 제어 문자(단락 내 특수문자 마커 등)를 제거"""
    return "".join(ch for ch in text if ch in ("\t", "\n") or ord(ch) >= 0x20)


class HWPParser(BaseParser):
    """hwp 5.0(구버전 OLE 바이너리) 파서 — olefile로 BodyText 스트림을 레코드 단위 파싱"""

    def get_file_type(self) -> FileType:
        return FileType.HWP

    def _section_streams(self, ole: "olefile.OleFileIO") -> list[str]:
        section_nums = []
        for entry in ole.listdir():
            if len(entry) == 2 and entry[0] == "BodyText" and entry[1].startswith("Section"):
                try:
                    section_nums.append(int(entry[1][len("Section"):]))
                except ValueError:
                    continue
        return [f"BodyText/Section{n}" for n in sorted(section_nums)]

    def get_page_count(self) -> int | None:
        try:
            with olefile.OleFileIO(str(self.file_path)) as ole:
                return len(self._section_streams(ole)) or None
        except Exception:
            return None

    def _is_compressed(self, ole: "olefile.OleFileIO") -> bool:
        header = ole.openstream("FileHeader").read()
        # FileHeader Properties 비트 필드(offset 36)의 bit0 = 스트림 압축 여부
        return bool(header[36] & 1)

    def _extract_section_paragraphs(self, data: bytes) -> list[str]:
        """BodyText 스트림을 레코드 단위로 순회하며 HWPTAG_PARA_TEXT 레코드의 텍스트를 추출"""
        paragraphs: list[str] = []
        size = len(data)
        i = 0
        while i + 4 <= size:
            header = struct.unpack_from("<I", data, i)[0]
            rec_type = header & 0x3FF
            rec_len = (header >> 20) & 0xFFF
            i += 4

            if rec_len == 0xFFF:
                if i + 4 > size:
                    break
                rec_len = struct.unpack_from("<I", data, i)[0]
                i += 4

            if i + rec_len > size:
                break

            if rec_type == _HWPTAG_PARA_TEXT:
                raw = data[i:i + rec_len]
                text = _clean_hwp_text(raw.decode("utf-16le", errors="ignore")).strip()
                if text:
                    paragraphs.append(text)

            i += rec_len

        return paragraphs

    def parse(self) -> DocumentExtractionResult:
        file_size = self.file_path.stat().st_size
        warnings: list[str] = []
        blocks: list[DocumentBlock] = []
        order = 0

        try:
            ole = olefile.OleFileIO(str(self.file_path))
        except Exception as e:
            raise CorruptedDocumentError(f"HWP 파일을 열 수 없습니다: {e}")

        with ole:
            if not ole.exists("FileHeader"):
                raise CorruptedDocumentError("HWP 파일 헤더(FileHeader)를 찾을 수 없습니다.")

            is_compressed = self._is_compressed(ole)
            sections = self._section_streams(ole)

            if not sections:
                raise CorruptedDocumentError(
                    "HWP에서 본문(BodyText/SectionN)을 찾을 수 없습니다. 손상된 파일일 수 있습니다."
                )

            document_id = self.generate_document_id(self.file_path)

            for idx, stream_name in enumerate(sections, start=1):
                raw = ole.openstream(stream_name).read()
                try:
                    data = zlib.decompress(raw, -15) if is_compressed else raw
                except zlib.error as e:
                    warnings.append(f"섹션 {idx} 압축 해제 실패로 건너뜁니다: {e}")
                    continue

                for para_text in self._extract_section_paragraphs(data):
                    blocks.append(DocumentBlock(
                        block_id=self.generate_block_id(
                            document_id, LocationType.DOCUMENT, idx, order,
                        ),
                        block_type=BlockType.TEXT,
                        content=para_text,
                        location_type=LocationType.DOCUMENT,
                        location_number=idx,
                        order=order,
                        metadata={},
                    ))
                    order += 1

        if len(blocks) == 0:
            raise EmptyDocumentError(
                "HWP에서 텍스트를 추출할 수 없습니다. 빈 문서이거나 손상된 파일일 수 있습니다."
            )

        return self.create_result(
            file_size=file_size,
            page_count=len(sections),
            blocks=blocks,
            warnings=warnings,
        )
