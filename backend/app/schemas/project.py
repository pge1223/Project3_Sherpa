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
    # 가은/Claude(2026-07-21): "내 프로젝트" 목록이 "공모전 분석"(작성 전) 완료 여부를
    # 판단할 신호가 없어서, 아이디어 확정 전 단계(분석은 끝났지만 회의 전)의 프로젝트까지
    # 실수로 안 보이게(혹은 삭제 대상으로 오판) 되던 문제 — announcement_analysis_cache
    # 존재 여부를 그대로 노출한다. POST /{id}/announcement-analysis를 다시 호출하면
    # LLM이 재실행되므로(캐시 없을 때) 목록에서 "확인"용으로 그 엔드포인트를 부를 수 없어
    # 여기 값을 그대로 싣는다.
    has_announcement_analysis: bool = False