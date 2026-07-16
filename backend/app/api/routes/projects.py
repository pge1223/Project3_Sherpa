from typing import Optional
from fastapi import APIRouter, HTTPException, Header
from datetime import datetime
from jose import jwt, JWTError
from app.schemas.project import ProjectCreateRequest, ProjectUpdateRequest, ProjectResponse
from app.repositories.project_repository import ProjectRepository
from app.models.project import ProjectModel
from app.config import settings

router = APIRouter(prefix="/projects", tags=["projects"])
project_repo = ProjectRepository()

# 가은/Claude (2026-07-15): 비회원 로그인은 별도 인증 호출 없이 그냥 Authorization
# 헤더를 안 보낸다 — 헤더가 없으면 401 대신 고정 게스트 사용자로 통과시킨다.
GUEST_USER_EMAIL = "guest@local"


# JWT에서 현재 유저 이메일 추출 (없으면 게스트)
def get_current_user(authorization: Optional[str]) -> str:
    if not authorization:
        return GUEST_USER_EMAIL
    try:
        token = authorization.replace("Bearer ", "")
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다")

# PRJ-001 프로젝트 생성
@router.post("/", response_model=ProjectResponse)
async def create_project(request: ProjectCreateRequest, authorization: Optional[str] = Header(None, alias="authorization")):
    user_email = get_current_user(authorization)

    project = ProjectModel(
        user_email=user_email,
        title=request.title,
        doc_type=request.doc_type,
        description=request.description,
    )
    result = await project_repo.create_project(project.to_dict())

    return ProjectResponse(
        id=str(result["_id"]),
        user_email=result["user_email"],
        title=result["title"],
        doc_type=result["doc_type"],
        description=result.get("description"),
        status=result["status"],
        created_at=result["created_at"],
        updated_at=result["updated_at"],
    )

# PRJ-002 프로젝트 목록 조회
@router.get("/", response_model=list[ProjectResponse])
async def get_projects(authorization: Optional[str] = Header(None, alias="authorization")):
    user_email = get_current_user(authorization)
    projects = await project_repo.find_by_user(user_email)

    return [
        ProjectResponse(
            id=str(p["_id"]),
            user_email=p["user_email"],
            title=p["title"],
            doc_type=p["doc_type"],
            description=p.get("description"),
            status=p["status"],
            created_at=p["created_at"],
            updated_at=p["updated_at"],
        )
        for p in projects
    ]

# PRJ-003 프로젝트 상세 조회
@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str, authorization: Optional[str] = Header(None, alias="authorization")):
    user_email = get_current_user(authorization)
    project = await project_repo.find_by_id_and_user(project_id, user_email)

    if not project:
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다")

    return ProjectResponse(
        id=str(project["_id"]),
        user_email=project["user_email"],
        title=project["title"],
        doc_type=project["doc_type"],
        description=project.get("description"),
        status=project["status"],
        created_at=project["created_at"],
        updated_at=project["updated_at"],
    )

# PRJ-004 프로젝트 삭제
@router.delete("/{project_id}")
async def delete_project(project_id: str, authorization: Optional[str] = Header(None, alias="authorization")):
    user_email = get_current_user(authorization)
    project = await project_repo.find_by_id_and_user(project_id, user_email)

    if not project:
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다")

    await project_repo.delete_project(project_id)
    return {"message": "프로젝트가 삭제되었습니다"}