from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException
from jose import jwt
from bcrypt import hashpw, checkpw, gensalt
from app.schemas.user import UserRegisterRequest, UserLoginRequest, TokenResponse
from app.repositories.user_repository import UserRepository
from app.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])
user_repo = UserRepository()

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
    return TokenResponse(access_token=token)