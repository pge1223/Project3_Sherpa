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

    # LLM 프로필 (가은/Claude, 2026-07-15, "다 이어버리자" — 윤한 확인 필요):
    # analyze_project()/reevaluate_reviewer()가 실제 OpenAI를 부르게 되면서 호출마다 비용이
    # 발생한다. LLM_PROFILE=dev(기본값, 저렴한 모델)로 두면 실수로 눌러도 싸게 끝나고,
    # 진짜 품질 확인이 필요할 때만 quality로 바꾸도록 두 세트를 분리했다.
    # 가은/Claude(2026-07-21): premium 단계 추가 — dev(개발·파싱·JSON 형식 테스트) /
    # quality(일반 사용자 피드백·MVP 데모, 기본으로 쓰는 실사용 품질) / premium(정말
    # 중요한 최종 시연·심층 회의만, gpt-5-nano처럼 느리지만 추론 품질이 높은 모델).
    # dev에 gpt-5-nano(추론 모델)를 넣으면 호출당 30~60초+ 걸려 일반 사용 흐름(주제
    # 아이디어 회의 등)이 느려지므로, 그런 무거운 모델은 premium에만 두고 quality는
    # 항상 빠른 비-추론 모델(gpt-4o-mini)로 유지한다.
    LLM_PROFILE: str = "dev"
    DEV_LLM_REVIEWER_MODEL: str = "gpt-4o-mini"
    DEV_LLM_CHAIR_MODEL: str = "gpt-4o-mini"
    QUALITY_LLM_REVIEWER_MODEL: str = "gpt-4o-mini"
    QUALITY_LLM_CHAIR_MODEL: str = "gpt-4o-mini"
    PREMIUM_LLM_REVIEWER_MODEL: str = "gpt-4o-mini"
    PREMIUM_LLM_CHAIR_MODEL: str = "gpt-4o-mini"

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

    # 용준/Claude(2026-07-20): 개발용 아이디어 발전 회의(ideation) 프리뷰 API 활성화 여부.
    # 기본값 False — main.py가 이 값이 True일 때만 ideation_preview 라우터를 등록한다.
    # 실제 OpenAI 호출이 들어가는 미검증 개발 도구라 운영 환경에서 실수로 켜지지 않게
    # 명시적으로 켜야만(backend/.env에 true) 동작한다.
    ENABLE_IDEATION_PREVIEW: bool = False

    # 용준/Claude(2026-07-21, 요청: 실시간 스트리밍): 대화형 아이디어 회의의 NDJSON 스트리밍
    # 응답(POST /ideation-conversation/{session_id}/reply/stream)을 켤지 여부. 기본값
    # True — 프리뷰 라우터를 활성화하면 현재 기본 UI의 실시간 응답도 함께 동작하게 한다.
    # ENABLE_IDEATION_PREVIEW와 별개 플래그로 둔 이유는, 프리뷰 라우터 자체는 켜져
    # 있어도(기존 동기식 API는 계속 쓰고 싶은 경우) 스트리밍은 아직 검증 전이라 끄고 싶을 수
    # 있어서다. 이 값이 False이면 /reply/stream 라우트는 (라우터 자체는 등록돼 있어도)
    # 404를 반환한다 — 기존 동기식 /reply는 이 플래그와 무관하게 항상 동작한다.
    ENABLE_IDEATION_STREAMING: bool = True

    # 아이디어 회의 화자·응답 대상·라우팅을 터미널에서 확인하는 개발 전용 로그. 사용자
    # 발언이 포함될 수 있어 운영 기본값은 항상 False다. delta 단위 로그는 별도 플래그를
    # 한 번 더 켜야 출력된다.
    ENABLE_IDEATION_TRACE_LOGS: bool = False
    IDEATION_TRACE_CONTENT_MAX_CHARS: int = 500
    IDEATION_TRACE_STREAM_DELTAS: bool = False

    # 용준/Claude(2026-07-22, 요청: RAG 품질 오프라인 평가 도구): Faithfulness/Persona
    # Evidence Fit LLM-as-judge 전용 모델. 실제 답변을 생성하는 모델(DEV_LLM_REVIEWER_MODEL
    # 등)과 분리해 둔다 — 평가자가 생성자와 같은 모델·같은 편향을 공유하지 않도록 하기
    # 위함이다(요청 7번). ai/rag/evaluation/rag_quality/cli.py만 읽는다.
    EVAL_LLM_MODEL: str = "gpt-4o-mini"

    class Config:
        env_file = str(_ENV_FILE)
        env_file_encoding = "utf-8"
        extra = "ignore"

    # 가은/Claude(2026-07-21): dev/quality/premium 3단계를 한 곳에서만 분기 — 이전엔
    # documents.py/meetings.py(3곳)/ideation_conversation_preview.py 각자
    # `"quality" if profile == "quality" else DEV_...` 식으로 흩어져 있어서 premium을
    # 추가하려면 매번 4곳을 고쳐야 했다.
    def reviewer_model(self) -> str:
        profile = (self.LLM_PROFILE or "dev").lower()
        if profile == "premium":
            return self.PREMIUM_LLM_REVIEWER_MODEL
        if profile == "quality":
            return self.QUALITY_LLM_REVIEWER_MODEL
        return self.DEV_LLM_REVIEWER_MODEL

    def chair_model(self) -> str:
        profile = (self.LLM_PROFILE or "dev").lower()
        if profile == "premium":
            return self.PREMIUM_LLM_CHAIR_MODEL
        if profile == "quality":
            return self.QUALITY_LLM_CHAIR_MODEL
        return self.DEV_LLM_CHAIR_MODEL


settings = Settings()
