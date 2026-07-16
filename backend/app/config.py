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

    # LLM 프로필 (가은/Claude, 2026-07-15, "다 이어버리자" — 윤한 확인 필요):
    # analyze_project()/reevaluate_reviewer()가 실제 OpenAI를 부르게 되면서 호출마다 비용이
    # 발생한다. LLM_PROFILE=dev(기본값, 저렴한 모델)로 두면 실수로 눌러도 싸게 끝나고,
    # 진짜 품질 확인이 필요할 때만 quality로 바꾸도록 두 세트를 분리했다.
    LLM_PROFILE: str = "dev"
    DEV_LLM_REVIEWER_MODEL: str = "gpt-5-nano"
    DEV_LLM_CHAIR_MODEL: str = "gpt-5-nano"
    QUALITY_LLM_REVIEWER_MODEL: str = "gpt-5-mini"
    QUALITY_LLM_CHAIR_MODEL: str = "gpt-5-mini"

    # NCP
    NCP_ACCESS_KEY: str = ""
    NCP_SECRET_KEY: str = ""
    NCP_BUCKET_NAME: str = ""

    # 재인/Claude (2026-07-16): 위원 발언 영상(TTS+MuseTalk 립싱크) 생성 서버 주소.
    # 실제 생성은 별도 MuseTalk 서버(현재 Colab, Cloudflare Quick Tunnel로 노출)가 하고,
    # backend/app/api/routes/media.py가 이 값으로 그 서버에 연결해 중계한다.
    # 세션마다 Cloudflare Quick Tunnel 주소가 바뀌므로 Colab 재기동할 때마다 갱신 필요.
    MEDIA_SERVICE_WS_URL: str = ""

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