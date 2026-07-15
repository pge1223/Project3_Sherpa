from pathlib import Path
from pydantic_settings import BaseSettings

# backend/.env 를 uvicorn 실행 위치(CWD)와 무관하게 항상 찾도록 절대경로 사용
# __file__ = backend/app/config.py  →  .parent.parent = backend/
_ENV_FILE = Path(__file__).parent.parent / ".env"


class Settings(BaseSettings):
    # 앱 기본 설정
    APP_NAME: str = "AI Review Board"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False

    # MongoDB
    MONGODB_URL: str = "mongodb://reviewboard_admin:reviewboard2026!@localhost:27017/?authSource=admin"
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