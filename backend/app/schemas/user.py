from typing import Optional
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


class Education(BaseModel):
    is_technical_major: bool = False
    field: str = ""
    degree: Optional[str] = None  # none|associate|bachelor|master|phd
    graduated: bool = False


class Experience(BaseModel):
    it_internship_months: int = 0
    competition_participations: int = 0
    awards: int = 0


class Github(BaseModel):
    connected: bool = False
    total_commits: int = 0
    primary_languages: list[str] = []
    has_backend_experience: bool = False
    relevant_projects: int = 0


class UserProfile(BaseModel):
    education: Education = Education()
    experience: Experience = Experience()
    github: Github = Github()


class UserProfileResponse(UserProfile):
    pass