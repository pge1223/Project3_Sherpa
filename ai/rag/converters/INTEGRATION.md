# HWP/HWPX 변환 — 통합 가이드 (backend/frontend 담당자용)

`ai/rag/converters/`는 HWP/HWPX 문서를 내부 처리용 PDF로 변환하는 모듈만 제공합니다.
`backend/app/api/routes/documents.py`(윤한 담당)와 프론트엔드 업로드 UI(가은 담당)는
이번 작업에서 수정하지 않았습니다 — 아래 내용을 참고해 각자 영역에서 연결해 주세요.

## 1. `_parse_chunk_and_index()` 통합 지점

현재 (`backend/app/api/routes/documents.py:69`):

```python
def _parse_chunk_and_index(document_id: str, project_id: str, file_path: str, filename: str) -> tuple[int, str]:
    extraction = extract_document(file_path)
    ...
```

권장 변경 (개념 예시, 실제 함수/변수명은 기존 코드에 맞춰 조정):

```python
from pathlib import Path
from ai.rag.converters import (
    convert_if_needed,
    cleanup_converted_file,
    DocumentConversionError,
    build_conversion_metadata,
)

def _parse_chunk_and_index(document_id: str, project_id: str, file_path: str, filename: str) -> tuple[int, str]:
    original_path = Path(file_path)
    conversion_result = None
    processing_path = original_path

    try:
        conversion_result = convert_if_needed(original_path)  # HWP/HWPX만 변환, 나머지는 None
        if conversion_result is not None:
            processing_path = conversion_result.converted_path
            # DB/문서 상태에 conversion metadata 기록 (아래 3번 참고)

        extraction = extract_document(processing_path)  # 기존 그대로 — 신규 파서 없음
        ...
    except DocumentConversionError as exc:
        # conversion_status = "failed", conversion_error = exc.user_message 로 저장
        # 청킹/임베딩은 실행하지 않고 여기서 반환/재발생
        raise
    finally:
        cleanup_converted_file(conversion_result)  # keep_converted_files=False면 삭제, 원본은 건드리지 않음
```

`convert_if_needed()`는 PDF/DOCX/PPTX면 `None`을 반환하므로 기존 경로는 그대로
유지됩니다. HWP/HWPX일 때만 변환이 실행됩니다.

## 2. 비동기/블로킹 관련

`_parse_chunk_and_index()`는 이미 `run_in_threadpool()`로 감싸 호출되고 있습니다
(`documents.py:249~251`). `HwpPdfConverter.convert()`는 동기 `subprocess.run()`을
쓰지만, 위 통합 지점이 이미 threadpool 안에서 실행되므로 이벤트 루프를 막지 않습니다.
별도로 `asyncio.create_subprocess_exec()` 등으로 바꿀 필요는 없습니다.

## 3. 문서 상태/metadata 저장

`ai/rag/converters/schemas.py`의 `build_conversion_metadata(conversion_result)`가
아래 dict 형태의 `DocumentConversionMetadata`를 반환합니다. 기존 `DocumentModel`에
metadata dict 필드가 있다면 그대로 병합해 저장하는 것을 권장합니다(신규 컬럼/migration
불필요):

```json
{
  "original_file_type": "hwp",
  "processing_file_type": "pdf",
  "conversion_status": "completed",
  "conversion_error": null,
  "converter_name": "libreoffice-headless",
  "conversion_duration_ms": 2480
}
```

PDF/DOCX/PPTX처럼 변환이 필요 없는 문서는 `conversion_status="not_required"`로
저장하면 됩니다(`ConversionStatus.NOT_REQUIRED`).

## 4. 원본 파일명/문서명 유지

- `conversion_result.original_path`가 원본 HWP/HWPX 경로, `converted_path`가 임시 PDF
  경로입니다. **사용자에게 보여주는 문서 제목·목록은 항상 원본 파일명
  (`filename`, 업로드 시점의 원본)을 사용**하고, `converted_path`의 파일명(`*_converted.pdf`
  또는 uuid 기반 임시 이름)은 응답에 노출하지 마세요.
- `extract_document(processing_path)`가 반환하는 `DocumentExtractionResult.file_name`은
  변환된 PDF 경로 기준이 될 수 있으므로, 문서 저장 시 `file_name`을 그대로 쓰지 말고
  업로드 시점의 원본 `filename`으로 덮어써 주세요.

## 5. 업로드 허용 확장자 (백엔드)

`.hwp`, `.hwpx`를 업로드 허용 목록에 추가하되, "업로드 허용 ≠ 변환 가능 보장"입니다.
변환기가 없거나 실패하면 문서 상태를 `failed`로 남기고 `exc.user_message`(아래 6번)를
사용자에게 보여주세요.

## 6. 사용자 오류 메시지

`ai/rag/converters/exceptions.py`의 모든 예외는 `.user_message` 속성에 프론트에 그대로
노출해도 되는 한국어 메시지를 담고 있습니다(서버 경로/명령어/stderr 없음):

```python
except DocumentConversionError as exc:
    return {"error": exc.user_message}   # 예: "HWP/HWPX 문서를 PDF로 변환하지 못했습니다..."
```

## 7. 프론트엔드 변경 (가은 담당)

- `frontend/src/utils/file.js`의 `ACCEPTED_DOCUMENT_EXTENSIONS`에 `'.hwp', '.hwpx'` 추가
- 안내 텍스트("PDF, DOCX, PPTX" → "PDF, DOCX, PPTX, HWP, HWPX")
- 변환 실패 시 백엔드가 내려주는 `user_message`를 그대로 표시(내부 문자열 재구성 불필요)

## 8. URL 첨부파일 경로 재사용

URL 로더가 다운로드한 첨부파일이 이후 공통 업로드 파이프라인(`_parse_chunk_and_index`류)을
타는 구조라면, 위 1번 통합 지점을 그대로 재사용하면 됩니다 — 별도 변환 로직을 URL 쪽에
새로 만들 필요가 없습니다. 이번 작업에서 URL 로더 코드 자체는 수정하지 않았습니다.
