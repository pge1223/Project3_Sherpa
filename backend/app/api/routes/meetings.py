"""
TEMPORARY STUB (가은/Claude, 2026-07-15)
=========================================
경이님의 ai/meeting/graph는 아직 M3(State 스키마 정의)까지만 완료되어 있고
M4(LangGraph 노드 조립·실제 회의 실행)는 진행 전이다 (ai/meeting/graph/state.py
주석 참고). 실제 위원회 분석 로직이 붙기 전까지, 프론트 "분석 시작" 흐름을
끊지 않기 위해 ai/meeting/tests/fixtures/final_meeting_result.v2.json
(review_output.schema.json v2.0.0에 맞는 최신 fixture)을 그대로 반환한다.

contracts/mocks/final_meeting_resault.json은 schema_version 1.0.0으로
현재 계약(v2.0.0)과 맞지 않아 이 스텁에는 쓰지 않았다.

경이님의 M4 그래프가 준비되면 analyze() 내부만 실제 LangGraph 호출로
교체하면 된다 — 라우트/응답 스키마는 그대로 유지.
"""
import json
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException
from jose import jwt, JWTError

from app.config import settings

router = APIRouter(prefix="/projects", tags=["meetings"])

_FIXTURE_PATH = (
    Path(__file__).resolve().parents[4]
    / "ai" / "meeting" / "tests" / "fixtures" / "final_meeting_result.v2.json"
)


def get_current_user(authorization: str) -> str:
    try:
        token = authorization.replace("Bearer ", "")
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다")


@router.post("/{project_id}/analyze")
async def analyze_project(project_id: str, authorization: str = Header(..., alias="authorization")):
    get_current_user(authorization)

    if not _FIXTURE_PATH.exists():
        raise HTTPException(status_code=500, detail="분석 결과 mock 파일을 찾을 수 없습니다.")

    fixture = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    result = fixture["data"]
    result = {**result, "project_id": project_id}
    return result
