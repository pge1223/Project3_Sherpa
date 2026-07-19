from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator

from ai.rag.loaders.schemas import UrlExtractionResult


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


# 가은/Claude(2026-07-19, INF-007 — fetch-url 색인 백그라운드화): UrlExtractionResult는
# ai/rag/loaders/schemas.py(용준 담당) 소유라 그 파일은 건드리지 않고, 백엔드 쪽에서
# 상속으로 필드만 확장한다. 색인(Chroma 임베딩)이 더 이상 응답을 막지 않으므로 — 이
# document_id/document_status로 GET /{project_id}/{document_id}/status(기존 DOC-004
# 엔드포인트, 신규 아님)를 폴링해서 색인 완료 여부를 알 수 있다. project_id를 안 보낸
# 호출(과거 호환, 조회만)이나 page_content가 없는 경우(직접 파일 링크 등)는 색인 자체가
# 없으므로 둘 다 None으로 남는다.
class FetchUrlResponse(UrlExtractionResult):
    document_id: Optional[str] = None
    document_status: Optional[str] = None
