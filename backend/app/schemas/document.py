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
