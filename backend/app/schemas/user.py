from typing import Literal, Optional
from pydantic import BaseModel, EmailStr


class UserRegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: str


class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    email: str
    name: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# 윤한/Claude(2026-07-21): 경이님 개인화 분류기(ai/meeting/scoring/personalization.py) 연동
# 계약 스펙 확정 — degree/graduation_status는 반드시 영문 enum(Literal)만 허용한다. 값이 아직
# 없는 사용자(마이페이지 미제출)를 위해 Optional로 두되, 값이 오면 반드시 이 enum 중 하나여야
# 하므로 한글이 들어오면 FastAPI가 422로 거부한다(별도 한글->영문 변환 로직은 두지 않음 —
# 가은님 프론트가 계약대로 영문 값을 보내는 것을 전제).
Degree = Literal["bachelor", "master", "phd", "other"]
GraduationStatus = Literal["graduated", "enrolled", "leave", "completed"]


class Education(BaseModel):
    is_technical_major: bool = False
    degree: Optional[Degree] = None
    graduation_status: Optional[GraduationStatus] = None


class Experience(BaseModel):
    internship_months: int = 0
    competition_count: int = 0
    award_count: int = 0


class Github(BaseModel):
    connected: bool = False
    public_repos: int = 0
    followers: int = 0
    total_stars: int = 0
    primary_languages: list[str] = []


class UserProfile(BaseModel):
    education: Education = Education()
    experience: Experience = Experience()
    github: Github = Github()


class UserProfileResponse(UserProfile):
    pass