from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings

# backend/.env 를 uvicorn 실행 위치(CWD)와 무관하게 항상 찾도록 절대경로 사용
# __file__ = backend/app/config.py  →  .parent.parent = backend/
_ENV_FILE = Path(__file__).parent.parent / ".env"


class Settings(BaseSettings):
    # 앱 기본 설정
    APP_NAME: str = "AI Review Board"
    APP_VERSION: str = "0.1.0"
    # VS Code/셸이 주입하는 범용 DEBUG 환경변수와 충돌하지 않도록
    # 백엔드 디버그 설정은 APP_DEBUG만 읽는다.
    DEBUG: bool = Field(default=False, validation_alias="APP_DEBUG")

    # MongoDB
    MONGODB_URL: str = "mongodb://localhost:27017"
    MONGODB_DB: str = "ai_review_board"

    # OpenAI
    OPENAI_API_KEY: str = ""

    # NCP
    NCP_ACCESS_KEY: str = ""
    NCP_SECRET_KEY: str = ""
    NCP_BUCKET_NAME: str = ""

    # RAG (Chroma)
    CHROMA_PERSIST_DIR: str = "./chroma_db"

    # JWT
    JWT_SECRET_KEY: str = "sherpa-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60

    class Config:
        env_file = str(_ENV_FILE)
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
