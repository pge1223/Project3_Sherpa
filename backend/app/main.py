import sys
from pathlib import Path

# backend/는 보통 이 디렉터리를 cwd로 uvicorn이 실행되어 레포 루트가 sys.path에 없다.
# ai.rag.documents 라우터가 ai.rag.* 를 import하므로 여기서 레포 루트를 추가해준다
# (ai/rag/tests/conftest.py의 동일 패턴 참고).
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.db.mongodb import connect_db, close_db
from app.api.routes.auth import router as auth_router
from app.api.routes.projects import router as project_router
from app.api.routes.documents import router as document_router
from app.api.routes.meetings import router as meeting_router
from app.api.routes.media import router as media_router  # 재인/Claude (2026-07-16): 위원 발언 영상 스트리밍 중계 (app/api/routes/media.py)
from app.core.logger import logger
app = FastAPI(
    title="AI Review Board API",
    description="RAG 기반 AI 심사위원회 시스템",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(project_router)
app.include_router(document_router)
app.include_router(meeting_router)
app.include_router(media_router)  # 재인/Claude (2026-07-16): /media/available-speakers, /media/stream

@app.on_event("startup")
async def startup():
    await connect_db()
    logger.info("AI Review Board API 서버 시작")


@app.on_event("shutdown")
async def shutdown():
    await close_db()
    logger.info("AI Review Board API 서버 종료")


@app.get("/")
async def root():
    return {"message": "AI Review Board API is running"}


@app.get("/health")
async def health_check():
    return {"status": "ok"}