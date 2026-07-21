from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Header, HTTPException
from jose import jwt, JWTError
from bcrypt import hashpw, checkpw, gensalt
from app.schemas.user import UserRegisterRequest, UserLoginRequest, TokenResponse
from app.repositories.user_repository import UserRepository
from app.repositories.login_log_repository import LoginLogRepository
from app.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])
user_repo = UserRepository()
login_log_repo = LoginLogRepository()

SECRET_KEY = settings.JWT_SECRET_KEY
ALGORITHM = settings.JWT_ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.JWT_EXPIRE_MINUTES


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


@router.post("/register")
async def register(request: UserRegisterRequest):
    existing = await user_repo.find_by_email(request.email)
    if existing:
        raise HTTPException(status_code=400, detail="이미 존재하는 이메일입니다")

    hashed_pw = hashpw(request.password.encode("utf-8"), gensalt()).decode("utf-8")

    user_data = {
        "email": request.email,
        "password": hashed_pw,
        "name": request.name,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "is_active": True,
    }

    await user_repo.create_user(user_data)
    return {"message": "회원가입 성공", "email": request.email}


@router.post("/login", response_model=TokenResponse)
async def login(request: UserLoginRequest):
    user = await user_repo.find_by_email(request.email)
    if not user:
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 틀렸습니다")

    if not checkpw(request.password.encode("utf-8"), user["password"].encode("utf-8")):
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 틀렸습니다")

    token = create_access_token({"sub": user["email"]})
    # 가은/Claude(2026-07-21): 로그인 성공마다 이력을 남긴다(로그인 기록 요청) — 토큰
    # 발급 실패로 이어지면 안 되니 로그인 자체를 막지 않는 순서로 둔다.
    await login_log_repo.create_log(user["email"])
    await user_repo.update_last_login(user["email"])
    return TokenResponse(access_token=token)


# 가은/Claude(2026-07-21): 본인 로그인 이력 조회 — 게스트(Authorization 헤더 없음)는
# 기록 자체가 없으므로 여기서는 guest 폴백 없이 토큰을 명시적으로 요구한다.
@router.get("/login-history")
async def get_login_history(authorization: Optional[str] = Header(None, alias="authorization")):
    if not authorization:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")
    try:
        token = authorization.replace("Bearer ", "")
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다")

    logs = await login_log_repo.find_by_email(email)
    return [{"email": log["email"], "logged_in_at": log["logged_in_at"]} for log in logs]