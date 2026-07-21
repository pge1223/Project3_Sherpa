from datetime import datetime
from typing import Optional, List
from bson import ObjectId

class ProjectModel:
    collection_name = "projects"

    def __init__(
        self,
        user_email: str,
        title: str,
        doc_type: str,
        description: Optional[str] = None,
        status: str = "pending",
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
        _id: Optional[ObjectId] = None,
        dynamic_rubric_mapping: Optional[dict] = None,
        announcement_analysis_cache: Optional[dict] = None,
        flow_mode: Optional[str] = None,
    ):
        self._id = _id
        self.user_email = user_email
        self.title = title
        self.doc_type = doc_type
        self.description = description
        self.status = status
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()
        # 가은/Claude(2026-07-18): 공고문에서 LLM으로 추출한 동적 rubric을 프로젝트당
        # 1회만 만들고 캐시해서 재사용하기 위한 필드(analyze/reevaluate 호출마다 다시
        # 추출하지 않는다) — ai/meeting/graph/rubric.py의 build_dynamic_rubric_mapping()이
        # 만든 mapping 전체(rubric_mapping_*.json과 동일 구조)를 그대로 저장한다.
        # 생성 시점엔 항상 None이고, backend/app/api/routes/meetings.py가
        # project_repo.update_project()로 나중에 채운다.
        self.dynamic_rubric_mapping = dynamic_rubric_mapping
        # 가은/Claude(2026-07-21): "공모전 분석" 화면(AnnouncementAnalysisResponse)을 매
        # 방문마다 새로 LLM 호출해서 계산하던 걸 프로젝트당 1회만 만들고 캐시 — 위
        # dynamic_rubric_mapping과 동일한 패턴(생성 시점엔 None, 나중에
        # documents.py가 project_repo.update_project()로 채운다).
        self.announcement_analysis_cache = announcement_analysis_cache
        # 가은/Claude(2026-07-21): EntryScreen에서 고른 "작성 전(pre)"/"작성 후(post)"를
        # 그대로 저장 — resume 시 이 값으로 mode를 복원한다("아이디어 확정"까지 가야만
        # 알 수 있던 기존 description 마커 방식을 대체).
        self.flow_mode = flow_mode

    def to_dict(self) -> dict:
        return {
            "user_email": self.user_email,
            "title": self.title,
            "doc_type": self.doc_type,
            "description": self.description,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "dynamic_rubric_mapping": self.dynamic_rubric_mapping,
            "announcement_analysis_cache": self.announcement_analysis_cache,
            "flow_mode": self.flow_mode,
        }