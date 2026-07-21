# 작성자: 재인/Claude (2026-07-21)
# 목적: "AI 피드백" 워크벤치(frontend/src/pages/board/WorkbenchScreen.jsx)가 원문에
#   정확한 하이라이트를 그릴 수 있도록, 위원 피드백이 기획서 원문 어디를 가리키는지
#   찾아준다.
#
# 원래는 GPT-4.1-mini에게 "원문 그대로 인용해달라"고 재질문하는 방식으로 만들었으나,
# 실측 비교 결과 청크 ID 직접 조회 방식(아래)이 AI 호출 없이도 항상 100% 정확한
# 원문을 반환해 더 낫다고 판단, 청크 방식만 최종으로 남긴다(GPT 재질문 방식은 삭제).
#
# 기존 경이님 파이프라인(ai/meeting/graph/evidence.py, reviewer_prompt.txt)의
# evidence.quote 문자열 자체를 하이라이트로 쓰지 않는 이유: reviewer_prompt.txt는
# "원문 의미를 바꾸지 않고 짧게 인용"만 요구해 글자 단위 정확한 인용을 보장하지 않는다.
# 대신 위원이 인용한 evidence.chunk_id로 벡터DB(Chroma)에서 청크 원문을 ID로 직접
# 조회한다 - 유사도 검색이 아니라 정확한 ID 매칭이라 항상 원문 그대로다.
# ChromaVectorStore.get_by_chunk_id는 ai/rag/retrieval/chroma_store.py(용준님 파일)에
# 추가한 메서드. documents.py의 _get_indexing_service() 싱글턴을 그대로 재사용하고
# 새 PersistentClient는 만들지 않는다(중복 client 생성 시 Windows에서 SQLite 잠김으로
# 멈추는 문제가 2026-07-18에 실제로 있었음).
from typing import Optional

from fastapi import APIRouter, Header
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api.routes.documents import get_current_user, verify_project_owner, _get_indexing_service

router = APIRouter(prefix="/workbench", tags=["workbench"])


class ChunkLookup(BaseModel):
    id: str
    chunk_id: str


class QuotesRequest(BaseModel):
    lookups: list[ChunkLookup]


class QuoteMatch(BaseModel):
    id: str
    quote: str
    found: bool


class QuotesResponse(BaseModel):
    matches: list[QuoteMatch]


@router.post("/{project_id}/quotes", response_model=QuotesResponse)
async def get_quotes(
    project_id: str,
    body: QuotesRequest,
    authorization: Optional[str] = Header(None, alias="authorization"),
):
    user_email = get_current_user(authorization)
    await verify_project_owner(project_id, user_email)

    if not body.lookups:
        return QuotesResponse(matches=[])

    vector_store = _get_indexing_service().vector_store

    def _fetch_all() -> list[QuoteMatch]:
        out: list[QuoteMatch] = []
        for lookup in body.lookups:
            text = vector_store.get_by_chunk_id(project_id, lookup.chunk_id)
            out.append(QuoteMatch(id=lookup.id, quote=text or "", found=bool(text)))
        return out

    results = await run_in_threadpool(_fetch_all)
    return QuotesResponse(matches=results)
