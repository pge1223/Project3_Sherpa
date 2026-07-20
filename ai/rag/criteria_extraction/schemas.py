"""
Notice Criteria Extraction Schemas
======================================
공고문에서 추출한 평가기준을 contracts/mocks/notice_criteria_*.json과 동일한 구조로
표현한다. domain/notice_document_id/notice_title/criteria[] 필드는 그 mock 파일과
이름·의미가 같고, meta는 (사람이 채우는 mock과 달리) 실행 시점에 자동 생성된다.

domain은 이 모듈이 분류하지 않는다 — 호출자가 프로젝트 생성 시점에 이미 아는 값
("government_support"/"competition" 등, ai.rag.orchestration.role_mapping과 동일한
값 체계)을 그대로 넘긴다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from ai.rag.chunking.schemas import Chunk

SCHEMA_NAME = "notice_criteria"
SCHEMA_VERSION = "1.0.0"

# backend/app/models/document.py에서 정의하는 document_role 값 중 공고문/평가기준
# 문서를 가리키는 값. 이 모듈은 그 문서만 대상으로 한다(문서 선별 자체는 호출자 책임).
EXPECTED_DOCUMENT_ROLE = "criteria"


class ExtractionStatus(str, Enum):
    """criteria 추출 최종 상태. 빈 criteria 배열만으로는 "정말 기준이 없음"과
    "애초에 대상이 아니었음"을 구분할 수 없어 상태를 별도로 남긴다."""

    EXTRACTED = "extracted"  # criteria 1개 이상 추출
    NOT_FOUND = "not_found"  # 후보 구간은 있었지만 LLM이 평가기준을 찾지 못함
    NO_CANDIDATE_SECTION = "no_candidate_section"  # 평가기준으로 보이는 구간 자체가 없음
    SKIPPED_WRONG_ROLE = "skipped_wrong_role"  # document_role != "criteria"


class Criterion(BaseModel):
    """단일 평가항목. contracts/mocks/notice_criteria_*.json의 criteria[] 원소와 구조가 같다."""

    criterion_id: str
    name: str
    description: str
    weight: Optional[float] = Field(
        None, description="배점. 공고문에 숫자로 명시되지 않으면 반드시 None(추측 금지)"
    )
    source_text: str = Field(..., description="근거가 된 원문 문장을 그대로 인용")
    page: Optional[int] = Field(None, description="원문 페이지/슬라이드 번호. 알 수 없으면 None")
    source_chunk_id: Optional[str] = Field(
        None, description="근거가 된 Chunk.chunk_id (재현·검증용 선택 필드, mock에는 없는 신규 필드)"
    )


class NoticeCriteriaMeta(BaseModel):
    """mock 파일의 meta(사람이 채운 프로젝트 설명)와 달리, 실행 시점 진단 정보를 담는다."""

    schema_name: str = SCHEMA_NAME
    schema_version: str = SCHEMA_VERSION
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    extraction_status: ExtractionStatus
    candidate_chunk_count: int = 0
    warnings: list[str] = Field(default_factory=list)


class NoticeCriteriaResult(BaseModel):
    """CriteriaExtractionService.extract()의 반환 스키마."""

    meta: NoticeCriteriaMeta
    domain: str
    notice_document_id: str
    notice_title: Optional[str] = None
    criteria: list[Criterion] = Field(default_factory=list)


class CriteriaExtractionRequest(BaseModel):
    """extract()의 입력. 특정 파일 형식(PDF/HWPX/URL)에 결합하지 않도록 이미 청킹까지
    끝난 Chunk 목록을 받는다 — ai.rag.chunking.chunk_document()의 출력이면 PDF/HWPX
    변환 후 PDF/URL 첨부/웹페이지 어느 경로로 만들어졌든 그대로 넘길 수 있다."""

    domain: str
    notice_document_id: str
    notice_title: Optional[str] = None
    chunks: list[Chunk]
    document_role: str = EXPECTED_DOCUMENT_ROLE

    @property
    def has_expected_role(self) -> bool:
        return self.document_role == EXPECTED_DOCUMENT_ROLE
