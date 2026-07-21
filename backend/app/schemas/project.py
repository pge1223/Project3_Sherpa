from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class ProjectCreateRequest(BaseModel):
    title: str
    doc_type: str
    description: Optional[str] = None
    # 가은/Claude(2026-07-21): 실측 요청 — 공모전 입력(EntryScreen)에서 "작성 전(주제
    # 발굴)"/"작성 후(문서 피드백)" 중 뭘 골랐는지가 어디에도 저장 안 돼서, "내 프로젝트"
    # 에서 다시 불러오면(resume) 어느 흐름이었는지 판단할 방법이 없었다("아이디어 확정"
    # 까지 끝낸 프로젝트만 description 마커로 겨우 알 수 있었음). "pre" | "post".
    flow_mode: Optional[str] = None

class ProjectUpdateRequest(BaseModel):
    title: Optional[str] = None
    doc_type: Optional[str] = None
    description: Optional[str] = None
    domain: Optional[str] = None
    flow_mode: Optional[str] = None

class ProjectResponse(BaseModel):
    id: str
    user_email: str
    title: str
    doc_type: str
    description: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: datetime
    flow_mode: Optional[str] = None