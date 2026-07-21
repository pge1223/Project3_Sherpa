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
import json
import logging
import os
from typing import Optional

from fastapi import APIRouter, Header
from openai import OpenAI
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from ai.rag.parsers import extract_document
from ai.rag.parsers.schemas import BlockType
from app.api.routes.documents import get_current_user, verify_project_owner, _get_indexing_service
from app.config import settings
from app.repositories.document_repository import DocumentRepository

router = APIRouter(prefix="/workbench", tags=["workbench"])
document_repo = DocumentRepository()
logger = logging.getLogger(__name__)


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


# 재인/Claude(2026-07-21): "맥락 이상 감지" — 사용자(2026-07-21)에게 확인받은 방향.
#
# 실측으로 시도해본 순서(전부 실제 테스트 문서 5개 - 정상 2개, 확 다른 주제가 섞인
# 것 2개, 같은 주제인데 타겟층만 살짝 어긋난 미묘한 것 1개 - 로 검증):
# 1) RAG 청크(chunk_size=800) 임베딩을 그대로 재활용해 평균에서 먼 것을 찾음 →
#    청크 하나가 여러 문단을 묶어버려서 신호가 묻힘, 아예 못 잡음.
# 2) 문단 단위로 다시 KURE-v1 임베딩 후 z-score로 후보만 추려 GPT에 재판단 시킴 →
#    "완전히 다른 주제"는 잡지만, "같은 주제인데 타겟층만 어긋난" 미묘한 경우는
#    임베딩 거리 자체가 크게 안 벌어져서 후보에도 못 들었다(실측: z=1.25, 임계값
#    미달). 임베딩 방식은 애초에 이런 미묘한 불일치를 잡을 수 있는 신호가 아니었다.
# 3) 그래서 통계 단계를 아예 버리고, GPT가 문서 전체를 한 번에 읽고 "앞뒤 안 맞는
#    문단" 후보를 찾게 한 뒤(1단계), 그 후보를 다시 깐깐한 2차 검토자 역할로
#    재검증시킨다(2단계) - 2026년 문서 수준 불일치 탐지 연구(arXiv:2601.02627)에서
#    "후보 추출 후 재검증하면 정확도가 오른다"는 결과와 같은 방향. temperature=0으로
#    고정해 실행마다 결과가 흔들리는 것도 줄였다. 5개 테스트 문서 전부(정상 2개는
#    깨끗하게, 확실한 이상 2개 + 미묘한 이상 1개는 전부 정확히) 통과 확인.
#
# LLM 호출은 문서당 최대 2번(후보 찾기 + 재검증, 후보가 없으면 1번만)이고, 결과는
# 문서에 캐싱해 재방문 시 다시 부르지 않는다.
_CONTEXT_CHECK_MIN_PARAGRAPHS = 3  # 문단이 이보다 적으면 "전체 흐름"이라 할 게 없어 스킵
_CONTEXT_CHECK_MAX_PARAGRAPHS_IN_PROMPT = 60  # 비정상적으로 큰 문서에 대한 방어적 상한
_CONTEXT_CHECK_MIN_PARAGRAPH_CHARS = 40  # 소제목처럼 문장이 아닌 짧은 조각은 판단 대상에서 제외


class ContextFinding(BaseModel):
    id: str
    quote: str
    message: str


class ContextCheckResponse(BaseModel):
    findings: list[ContextFinding]


async def _find_target_document(project_id: str) -> Optional[dict]:
    documents = await document_repo.find_by_project_id(project_id)
    targets = [d for d in documents if d.get("document_role", "target") == "target"]
    return targets[0] if targets else None


def _extract_body_paragraphs(file_path: str) -> list[str]:
    """서술형 TEXT 블록만 문단 후보로 쓴다 - LIST(글머리 기호 항목)나 TITLE은 원래
    짧고 단편적이라 "앞뒤 문맥이 맞는지" 판단 대상으로 적절하지 않다."""
    result = extract_document(file_path)
    paragraphs = []
    for block in result.blocks:
        if block.block_type != BlockType.TEXT:
            continue
        content = block.content.strip()
        if len(content) < _CONTEXT_CHECK_MIN_PARAGRAPH_CHARS:
            continue
        paragraphs.append(content)
    return paragraphs


def _build_context_find_prompt(paragraphs: list[str]) -> str:
    numbered = "\n\n".join(
        f"{i + 1}. {text[:400]}" for i, text in enumerate(paragraphs[:_CONTEXT_CHECK_MAX_PARAGRAPHS_IN_PROMPT])
    )
    return f"""당신은 사업계획서를 처음부터 끝까지 꼼꼼히 읽는 편집자입니다. 아래 문단들을
전부 읽고, 문서 전체의 흐름과 앞뒤가 안 맞는 부분이 있는지 찾으세요. 특히 이 두
가지를 중점적으로 확인하세요:
1) 완전히 다른 업종/주제가 맥락 없이 끼어든 경우
2) 문서 전체에서 대상 독자·타겟층(예: 연령대, 이용자 집단)이 문단마다 다르게
   설정되어 있는 경우 - 이건 자연스러운 "확장"이 아니라 "불일치"이니 반드시
   지적하세요.
단순히 문체가 다르거나 수치/일정표처럼 원래 그런 문단이라면 지적하지 마세요.

[전체 문단]
{numbered}

다음 JSON 형식으로만 응답하세요:
{{
  "candidates": [
    {{"index": 문단 번호, "issue": "무엇이 왜 안 맞는지 한 문장"}}
  ]
}}
이상이 없으면 candidates를 빈 배열로 두세요."""


def _build_context_verify_prompt(paragraphs: list[str], candidates: list[dict]) -> str:
    lines = []
    for c in candidates:
        idx = c["index"] - 1
        text = paragraphs[idx][:200] if 0 <= idx < len(paragraphs) else ""
        lines.append(f'- {c["index"]}번 문단: "{text}"\n  동료가 제시한 근거: {c.get("issue", "")}')
    candidates_text = "\n\n".join(lines)

    return f"""방금 동료 편집자가 사업계획서에서 아래와 같은 "앞뒤가 안 맞는 문단"을
찾아냈습니다. 당신은 이번엔 2차 검토자입니다. 각 후보에 대해 실제로 문제인지
판단하세요.

다음 두 경우는 명백한 문제이니 반드시 동의(confirmed=true)하세요:
- 완전히 다른 업종/주제(예: 반려동물, 암호화폐, 요리)가 섞여 있는 경우
- 문서 앞부분에서 설정한 대상 독자·타겟층(예: "청년층")과 다른 대상(예: "노년층")을
  별도로 언급하는 경우 - "관련이 있을 수도 있다"는 이유로 봐주지 마세요. 사업계획서는
  타겟이 명확해야 하고, 다른 타겟이 갑자기 등장하는 것 자체가 이미 문제입니다.

반대로 같은 주제·같은 대상 안에서 표현 방식이나 문체 차이 정도라면
기각(confirmed=false)하세요.

{candidates_text}

각 후보에 대해 다음 JSON 형식으로만 응답하세요:
{{
  "verified": [
    {{"index": 문단 번호, "confirmed": true 또는 false, "reason": "동의/기각 이유 한 문장"}}
  ]
}}"""


def _call_context_check_llm(prompt: str) -> str:
    # temperature=0: 이 판단은 창작이 아니라 분류(맞다/아니다)라, 매번 결과가 흔들리면
    # 안 된다 - 재인/Claude(2026-07-21) 실측으로 기본 temperature에서 같은 문서·같은
    # 프롬프트로도 후보가 나왔다 안 나왔다 하는 걸 확인해서 고정했다.
    profile = (settings.LLM_PROFILE or "dev").lower()
    model = settings.QUALITY_LLM_REVIEWER_MODEL if profile == "quality" else settings.DEV_LLM_REVIEWER_MODEL
    client = OpenAI(api_key=settings.OPENAI_API_KEY, max_retries=1)
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0,
    )
    return resp.choices[0].message.content


@router.get("/{project_id}/context-check", response_model=ContextCheckResponse)
async def get_context_check(
    project_id: str,
    authorization: Optional[str] = Header(None, alias="authorization"),
):
    user_email = get_current_user(authorization)
    await verify_project_owner(project_id, user_email)

    document = await _find_target_document(project_id)
    if document is None:
        return ContextCheckResponse(findings=[])

    cached = document.get("context_check_cache")
    if cached:
        logger.info("[context-check] document_id=%s 캐시된 결과 재사용", document["_id"])
        return ContextCheckResponse(**cached)

    document_id = document["_id"]
    file_path = document.get("file_path")

    async def _cache_and_return(response: ContextCheckResponse) -> ContextCheckResponse:
        await document_repo.update_fields(document_id, {"context_check_cache": response.model_dump()})
        return response

    if not file_path or not os.path.exists(file_path):
        return await _cache_and_return(ContextCheckResponse(findings=[]))

    paragraphs = await run_in_threadpool(_extract_body_paragraphs, file_path)
    if len(paragraphs) < _CONTEXT_CHECK_MIN_PARAGRAPHS:
        return await _cache_and_return(ContextCheckResponse(findings=[]))

    numbered_paragraphs = paragraphs[:_CONTEXT_CHECK_MAX_PARAGRAPHS_IN_PROMPT]

    find_raw = await run_in_threadpool(_call_context_check_llm, _build_context_find_prompt(paragraphs))
    try:
        find_parsed = json.loads(find_raw)
    except (json.JSONDecodeError, TypeError):
        find_parsed = {}

    candidates = [
        c for c in ((find_parsed.get("candidates") if isinstance(find_parsed, dict) else None) or [])
        if isinstance(c, dict) and isinstance(c.get("index"), int) and 1 <= c["index"] <= len(numbered_paragraphs)
    ]
    if not candidates:
        return await _cache_and_return(ContextCheckResponse(findings=[]))

    verify_raw = await run_in_threadpool(
        _call_context_check_llm, _build_context_verify_prompt(numbered_paragraphs, candidates)
    )
    try:
        verify_parsed = json.loads(verify_raw)
    except (json.JSONDecodeError, TypeError):
        verify_parsed = {}

    candidate_indices = {c["index"] for c in candidates}
    findings: list[ContextFinding] = []
    for item in (verify_parsed.get("verified") if isinstance(verify_parsed, dict) else None) or []:
        if not isinstance(item, dict) or not item.get("confirmed"):
            continue
        index = item.get("index")
        if not isinstance(index, int) or index not in candidate_indices:
            continue  # 2차 검토자가 원래 후보에 없던 번호를 임의로 답하면 무시
        reason = str(item.get("reason") or "").strip()
        if not reason:
            continue
        paragraph_index = index - 1
        findings.append(ContextFinding(
            id=f"context-{paragraph_index}",
            quote=numbered_paragraphs[paragraph_index],
            message=reason,
        ))

    return await _cache_and_return(ContextCheckResponse(findings=findings))
