# 윤한/Claude(2026-07-21): RPT-004 버전 비교 API. 두 회의 결과(review_output v2 문서)를
# meeting_id로 각각 꺼내 ai/meeting/scoring/comparison.py(경이)의 순수 비교 로직에
# 넘기기만 한다 — 비교 계산 자체는 이 파일 책임이 아니다.
from typing import Optional

from fastapi import APIRouter, Header, HTTPException

from ai.meeting.scoring import build_revision_comparison
from app.api.routes.documents import get_current_user
from app.repositories.meeting_repository import MeetingRepository
from app.repositories.project_repository import ProjectRepository

router = APIRouter(prefix="/projects", tags=["comparison"])
meeting_repo = MeetingRepository()
project_repo = ProjectRepository()


@router.get("/{project_id}/comparison")
async def get_revision_comparison(
    project_id: str,
    before: str,
    after: str,
    authorization: Optional[str] = Header(None, alias="authorization"),
):
    user_email = get_current_user(authorization)

    project = await project_repo.find_by_id_and_user(project_id, user_email)
    if project is None:
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")

    before_meeting = await meeting_repo.find_by_meeting_id(project_id, before)
    if before_meeting is None:
        raise HTTPException(status_code=404, detail=f"수정 전 회의 결과(meeting_id={before})를 찾을 수 없습니다.")

    after_meeting = await meeting_repo.find_by_meeting_id(project_id, after)
    if after_meeting is None:
        raise HTTPException(status_code=404, detail=f"수정 후 회의 결과(meeting_id={after})를 찾을 수 없습니다.")

    if not before_meeting.get("score_result") or not after_meeting.get("score_result"):
        raise HTTPException(status_code=400, detail="아직 채점이 끝나지 않은 회의는 비교할 수 없습니다.")

    return build_revision_comparison(before_meeting, after_meeting)
