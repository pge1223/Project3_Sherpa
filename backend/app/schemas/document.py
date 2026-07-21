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


# 가은/Claude(2026-07-21): "공모전 분석" 화면(사용자 UX 스펙, 2026-07-21) — 공고문에서
# 실제로 확인되는 사실(official_facts)과 AI가 추론한 전략적 분석(strategic_analysis)을
# 분리해서 반환한다. 공고문에 없는 정보를 지어내지 않는다 — 못 찾은 필드는 빈 배열/
# "미공개" 문자열로 명시한다(값을 비워두는 대신 근거 없음 자체를 표시).
class OfficialFacts(BaseModel):
    eligibility: list[str] = []
    deadline: str = "미공개"
    submission_requirements: list[str] = []
    evaluation_criteria: list[str] = []
    disqualification_rules: list[str] = []


class StrategicAnalysis(BaseModel):
    core_intent: str = ""
    winning_points: list[str] = []
    recommended_direction: list[str] = []
    risk_flags: list[str] = []


class AnnouncementEvidence(BaseModel):
    claim: str
    # "announcement": 공고문 원문에 직접 근거가 있음 / "inference": AI가 추론한 내용(원문에 명시 없음)
    source_type: str
    location: Optional[str] = None
    confidence: str = "medium"


# 가은/Claude(2026-07-21): kyh님이 크롤링(contest_works, 소통혁신24)해서 category/
# source_org까지 채운(scripts/classify_contest_works.py) 수상작 아카이브가 생겨서, 여기
# 붙였던 "데이터 소스 자체가 없다"는 이전 제약은 더 이상 사실이 아니다. LLM이 원문에서
# 안 나오는 개별 수상작을 지어내는 건 여전히 막고, 대신 실제 DB에서 조회한 값만 담는다
# (없으면 has_similar_case_data=False로 그대로 "미확보" 상태를 보여준다).
class SimilarWork(BaseModel):
    title: str
    source_org: str = ""
    award_grade: str = ""
    selection_status: str = ""  # "winner" | "candidate"


class AnnouncementAnalysisResponse(BaseModel):
    has_announcement: bool
    # 가은/Claude(2026-07-21): 실측 요청 — 화면 제목에 실제 공모전명이 나오게. 페이지
    # <title>은 "공지사항 - 부서명" 같은 사이트 boilerplate인 경우가 많아 신뢰 못 함
    # (실측: 외교부 공고 사례) — 본문에서 LLM이 직접 뽑는다. 못 찾으면 빈 문자열.
    announcement_title: str = ""
    official_facts: Optional[OfficialFacts] = None
    strategic_analysis: Optional[StrategicAnalysis] = None
    evidence: list[AnnouncementEvidence] = []
    has_similar_case_data: bool = False
    similar_works: list[SimilarWork] = []
    source_document_names: list[str] = []
