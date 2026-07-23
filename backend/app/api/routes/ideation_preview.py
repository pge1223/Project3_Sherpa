# 작성자: 용준/Claude(2026-07-20)
# 목적: 개발용 "아이디어 발전 회의(ideation)" 프리뷰 API. planning_expert -> dev_expert ->
#       planning_expert_revise -> facilitator 흐름이 실제 LLM 호출과 웹 화면까지 올바르게
#       연결되는지 검증하기 위한 것으로, 정식 API가 아니다.
#
# 정식 기능과의 차이(요청 범위 그대로):
#   - MongoDB에 저장하지 않는다(MeetingModel/MeetingRepository를 쓰지 않는다).
#   - 사용자 답변 재개(continue_ideation_meeting)는 다루지 않는다 — 한 번의 POST로 끝까지
#     돌리거나, facilitator가 사용자 질문이 필요하다고 판단하면 그 상태로 멈춘 채 반환한다.
#   - 기존 심사형 analyze_project()/run_meeting()(meetings.py)은 전혀 건드리지 않는다.
#
# settings.ENABLE_IDEATION_PREVIEW가 False(기본값)면 main.py가 이 라우터 자체를 앱에
# 등록하지 않는다 — 운영 환경에서 실수로 노출/실행되지 않도록 라우팅 단계에서 막는다.
from __future__ import annotations

import logging
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from openai import OpenAI

from app.core.llm import trace_openai_client
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ideation-preview (dev only)"])

# meetings.py와 동일한 방식으로 ai/meeting을 sys.path에 올린다(같은 디렉터리 깊이라
# parents[4] 그대로 재사용) — import 순서와 무관하게 이 파일 단독으로도 동작하게 한다.
_MEETING_DIR = Path(__file__).resolve().parents[4] / "ai" / "meeting"
if str(_MEETING_DIR) not in sys.path:
    sys.path.insert(0, str(_MEETING_DIR))

from graph import start_ideation_meeting  # noqa: E402

# use_rag=True일 때 근거 검색에 쓸 RoleAwareRetrievalService 싱글턴 — meetings.py가 앱
# 시작 시 이미 만들어둔 것을 그대로 재사용한다(KUREEmbedder 중복 로딩 방지,
# meetings.py의 _role_retrieval_service 생성부 주석과 동일한 이유).
from app.api.routes.meetings import _role_retrieval_service  # noqa: E402

# 비용/무한 실행 방지 상한. 요청 max_rounds가 이보다 크면 잘라낸다(요청 12번).
_MAX_PREVIEW_ROUNDS = 3
# 라운드당 최대 4콜(기획/개발/기획 재수정/진행자) + 최종 종합 1콜 여유를 감안한 호출 상한.
_MAX_PREVIEW_LLM_CALLS = 20


class IdeationPreviewRequest(BaseModel):
    competition_name: str
    competition_document: str
    user_idea: str
    max_rounds: int = 1
    use_rag: bool = False
    project_id: Optional[str] = None


def _build_preview_llm_call(meeting_id: str):
    """개발용 실제 OpenAI 호출. meetings.py::_build_real_llm_call()과 같은 안전장치
    (max_retries=1, 호출 상한, JSON 응답 강제)를 쓰되, 위원장/위원 모델을 구분하지 않고
    항상 DEV_LLM_REVIEWER_MODEL(가장 저렴한 dev 모델)만 쓴다 — 이건 품질 검증이 아니라
    파이프라인 연결 검증용이다."""
    client = trace_openai_client(OpenAI(api_key=settings.OPENAI_API_KEY, max_retries=1))
    call_count = {"n": 0}

    def llm_call(prompt: str) -> str:
        call_count["n"] += 1
        if call_count["n"] > _MAX_PREVIEW_LLM_CALLS:
            raise RuntimeError(
                f"[{meeting_id}] 프리뷰 LLM 호출 상한({_MAX_PREVIEW_LLM_CALLS}회) 초과 — "
                "루프 또는 재시도 폭주 의심, 중단합니다."
            )
        started = time.time()
        resp = client.chat.completions.create(
            model=settings.DEV_LLM_REVIEWER_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        elapsed = time.time() - started
        logger.info(
            "[%s] 프리뷰 LLM 호출 #%d elapsed=%.1fs usage=%s",
            meeting_id,
            call_count["n"],
            elapsed,
            resp.usage.model_dump() if resp.usage else None,
        )
        return resp.choices[0].message.content

    return llm_call


@router.post("/ideation-preview")
async def preview_ideation_meeting(request: IdeationPreviewRequest):
    if not settings.ENABLE_IDEATION_PREVIEW:
        raise HTTPException(status_code=404, detail="Not Found")

    if request.use_rag and not request.project_id:
        raise HTTPException(status_code=400, detail="use_rag=true이면 project_id가 필요합니다.")

    effective_max_rounds = max(1, min(request.max_rounds, _MAX_PREVIEW_ROUNDS))
    meeting_id = f"IDEA-PREVIEW-{uuid.uuid4().hex[:8]}"

    # 요청값을 프롬프트 문자열로 직접 이어붙이지 않는다 — dict로만 조립해서
    # start_ideation_meeting()에 넘기면 ai/meeting/prompts/prompt_loader.py의
    # build_ideation_turn_prompt/build_ideation_facilitator_prompt/
    # build_ideation_synthesis_prompt가 <<NOTICE_AND_CRITERIA_JSON>>/<<USER_IDEA_JSON>>
    # 토큰으로 JSON 직렬화해 삽입한다(요청 7번).
    notice_and_criteria = {
        "competition_name": request.competition_name,
        "notice_document": request.competition_document,
    }
    user_idea = {"description": request.user_idea}

    evidence_lookup = None
    if request.use_rag:
        from ai.rag.orchestration.ideation_evidence_service import make_ideation_evidence_lookup

        evidence_lookup = make_ideation_evidence_lookup(
            project_id=request.project_id,
            role_retrieval_service=_role_retrieval_service,
            top_k=5,
        )

    llm_call = _build_preview_llm_call(meeting_id)

    logger.info(
        "[ideation-preview] 시작 meeting_id=%s max_rounds=%d use_rag=%s",
        meeting_id,
        effective_max_rounds,
        request.use_rag,
    )
    try:
        document = await run_in_threadpool(
            start_ideation_meeting,
            meeting_id=meeting_id,
            project_id=request.project_id or "IDEATION_PREVIEW",
            notice_and_criteria=notice_and_criteria,
            user_idea=user_idea,
            llm_call=llm_call,
            max_rounds=effective_max_rounds,
            evidence_lookup=evidence_lookup,
        )
    except Exception:
        logger.exception("[ideation-preview] 실행 실패 meeting_id=%s", meeting_id)
        return {
            "status": "failed",
            "current_round": None,
            "turns": [],
            "pending_question": None,
            "facilitator_summary": None,
            "final_proposal": None,
            "error": {
                "code": "IDEATION_PREVIEW_FAILED",
                "message": "회의 실행 중 오류가 발생했습니다. 서버 로그를 확인하세요.",
            },
        }

    logger.info(
        "[ideation-preview] 완료 meeting_id=%s status=%s round=%s turns=%d",
        meeting_id,
        document["status"],
        document["round"],
        len(document["turns"]),
    )

    return {
        "status": document["status"],
        "current_round": document["round"],
        "turns": document["turns"],
        "pending_question": document["pending_question"],
        "facilitator_summary": {
            "consensus": document["consensus"],
            "unresolved_issues": document["unresolved_issues"],
        },
        "final_proposal": document["idea_proposal"],
        "error": document["error"],
    }
