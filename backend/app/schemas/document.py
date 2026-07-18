from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator


class DocumentResponse(BaseModel):
    id: str
    project_id: str
    user_email: str
    original_filename: str
    stored_filename: str
    file_path: str
    file_size: int
    mime_type: str
    source_type: str
    status: str
    created_at: datetime
    updated_at: datetime
    document_role: str = "target"
    # 가은/Claude(2026-07-16): HWP/HWPX 변환 결과(성공/실패/불필요) — 프론트가 실패 시
    # conversion_metadata.conversion_error(user_message)를 그대로 보여준다.
    conversion_metadata: Optional[dict] = None
    # 가은/Claude(2026-07-18): URL 공고문 수집 시 발견됐지만 자동으로 못 읽은 첨부파일
    # (HWP/HWPX) — 프론트가 "직접 받아서 파일 업로드 탭으로 올려주세요" 안내 + 다운로드
    # 링크를 보여준다. [{"url", "file_name", "reason"}]
    unsupported_attachments: Optional[list[dict]] = None


class FetchUrlRequest(BaseModel):
    url: str
    # 가은/Claude (2026-07-15): project_id가 있으면 RAG 색인까지 하고 documents 컬렉션에
    # document_role="criteria"로 저장한다. 없으면(과거 호출 호환) 조회만 하고 저장하지 않는다.
    project_id: Optional[str] = None

    @field_validator("url")
    @classmethod
    def _url_must_not_be_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("url은 빈 문자열일 수 없습니다")
        return v
