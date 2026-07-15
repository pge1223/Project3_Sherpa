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


class FetchUrlRequest(BaseModel):
    url: str

    @field_validator("url")
    @classmethod
    def _url_must_not_be_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("url은 빈 문자열일 수 없습니다")
        return v
