from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 앱 기본 설정
    APP_NAME: str = "AI Review Board"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False

    # MongoDB
    MONGODB_URL: str = "mongodb://sherpa_admin:sherpa2026!@localhost:27017"
    MONGODB_DB: str = "ai_review_board"

    # OpenAI
    OPENAI_API_KEY: str = ""

    # NCP
    NCP_ACCESS_KEY: str = ""
    NCP_SECRET_KEY: str = ""
    NCP_BUCKET_NAME: str = ""
    # JWT
    JWT_SECRET_KEY: str = "sherpa-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()