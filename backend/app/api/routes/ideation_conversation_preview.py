# 작성자: 용준/Claude(2026-07-20)
# 목적: 개발용 "아이디어 발전 회의(ideation)" 대화형(conversational) 프리뷰 API.
#       기존 배치형 프리뷰(ideation_preview.py, POST /ideation-preview 한 번 호출로 전체
#       회의를 끝까지 돌림)와 달리, 이 라우터는 질문 하나마다 사용자 응답을 기다리는
#       구조를 검증하기 위한 것이다 — 역시 정식 API가 아니다.
#
# 정식 기능과의 차이(요청 범위 그대로):
#   - MongoDB에 저장하지 않는다. 세션은 프로세스 메모리에만 있는 in-memory 저장소
#     (_SessionStore)에 보관되며, 서버가 재시작되면 모든 세션이 사라진다.
#   - TTL(_SESSION_TTL_SECONDS)이 지난 세션은 자동 만료되고, 세션 수가 상한
#     (_MAX_SESSIONS)을 넘으면 가장 오래된 세션부터 제거한다(둘 다 메모리 누수 방지).
#   - 기존 배치형 /ideation-preview, 심사형 analyze_project()/run_meeting()은 전혀
#     건드리지 않는다.
#
# settings.ENABLE_IDEATION_PREVIEW가 False(기본값)면 main.py가 이 라우터 자체를 앱에
# 등록하지 않는다 — ideation_preview.py와 같은 플래그를 공유한다(둘 다 같은 "개발용
# ideation 프리뷰" 묶음이라 별도 플래그를 새로 만들지 않았다).
from __future__ import annotations

import logging
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from openai import OpenAI
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ideation-conversation", tags=["ideation-conversation-preview (dev only)"])

# ideation_preview.py와 동일한 방식으로 ai/meeting을 sys.path에 올린다.
_MEETING_DIR = Path(__file__).resolve().parents[4] / "ai" / "meeting"
if str(_MEETING_DIR) not in sys.path:
    sys.path.insert(0, str(_MEETING_DIR))

from graph import (  # noqa: E402
    IdeationConvState,
    active_stage_for,
    finalize_ideation_conversation,
    reply_ideation_conversation,
    start_ideation_conversation,
)

from app.api.routes.meetings import _role_retrieval_service  # noqa: E402

# ---------------------------------------------------------------------------
# 안전장치 상한값 (요청 "개발용 API" 절)
# ---------------------------------------------------------------------------
_SESSION_TTL_SECONDS = 30 * 60  # 30분 이상 응답 없는 세션은 만료된 것으로 간주한다.
_MAX_SESSIONS = 200  # 이 이상이면 가장 오래전에 활동한 세션부터 제거한다(메모리 상한).
_MAX_ROUNDS_CAP = 3  # 요청 max_rounds가 이보다 크면 잘라낸다.
_MAX_TEXT_LENGTH = 2000  # 공모전 설명/아이디어/답변 1건당 최대 길이(문자 수).
_MAX_LLM_CALLS_PER_REQUEST = 6  # 한 HTTP 요청에서 허용하는 최대 LLM 호출 수(질문1 / 답변당 최대 3 / 종합1 기준 여유).


class _SessionRecord:
    __slots__ = ("state", "created_at", "last_active_at")

    def __init__(self, state: IdeationConvState):
        self.state = state
        now = time.time()
        self.created_at = now
        self.last_active_at = now


class _SessionStore:
    """개발용 인메모리 세션 저장소. 스레드 세이프하게(threading.Lock) TTL 만료와 최대
    세션 수 제한을 처리한다 — 정식 서비스에서는 MongoDB 등 영속 저장소로 교체돼야 한다
    (최종 보고서 "정식 전환 시 교체할 임시 코드" 참고)."""

    def __init__(self, ttl_seconds: int, max_sessions: int):
        self._ttl_seconds = ttl_seconds
        self._max_sessions = max_sessions
        self._sessions: dict[str, _SessionRecord] = {}
        self._lock = threading.Lock()

    def _sweep_expired_locked(self) -> None:
        now = time.time()
        expired = [
            sid for sid, rec in self._sessions.items() if now - rec.last_active_at > self._ttl_seconds
        ]
        for sid in expired:
            del self._sessions[sid]

    def _evict_oldest_locked(self) -> None:
        while len(self._sessions) >= self._max_sessions:
            oldest_id = min(self._sessions, key=lambda sid: self._sessions[sid].last_active_at)
            del self._sessions[oldest_id]

    def create(self, state: IdeationConvState) -> None:
        with self._lock:
            self._sweep_expired_locked()
            self._evict_oldest_locked()
            self._sessions[state["session_id"]] = _SessionRecord(state)

    def get(self, session_id: str) -> IdeationConvState:
        with self._lock:
            self._sweep_expired_locked()
            record = self._sessions.get(session_id)
            if record is None:
                raise KeyError(session_id)
            return record.state

    def update(self, session_id: str, state: IdeationConvState) -> None:
        with self._lock:
            record = self._sessions.get(session_id)
            if record is None:
                # 갱신 도중 TTL 만료로 사라졌을 수 있다 — 새로 만들어 계속 진행한다.
                record = _SessionRecord(state)
                self._sessions[session_id] = record
            record.state = state
            record.last_active_at = time.time()


_store = _SessionStore(_SESSION_TTL_SECONDS, _MAX_SESSIONS)


def _require_preview_enabled() -> None:
    if not settings.ENABLE_IDEATION_PREVIEW:
        raise HTTPException(status_code=404, detail="Not Found")


def _clamp_text(value: str, field_name: str) -> str:
    value = (value or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail=f"{field_name}은(는) 비어 있을 수 없습니다.")
    if len(value) > _MAX_TEXT_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name}은(는) 최대 {_MAX_TEXT_LENGTH}자까지 입력할 수 있습니다.",
        )
    return value


def _clamp_optional_text(value: str, field_name: str) -> str:
    """_clamp_text와 달리 빈 문자열을 허용한다 — user_idea가 이 경우다(요청 6번: "user_idea가
    빈 문자열이어도 start API가 400을 반환하지 않음"). 길이 상한만 검사한다. 빈 값은
    initial_conv_state()가 discovery 모드로 해석한다(ideation_conv_state.py 참고)."""
    value = (value or "").strip()
    if len(value) > _MAX_TEXT_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name}은(는) 최대 {_MAX_TEXT_LENGTH}자까지 입력할 수 있습니다.",
        )
    return value


def _build_llm_call(session_id: str, model: str):
    """실제 OpenAI 호출. 요청 1건당 LLM 호출 횟수 상한(_MAX_LLM_CALLS_PER_REQUEST)을 두어
    라우팅 버그로 인한 루프·과호출을 방지한다(ideation_preview.py의 동일 안전장치와 같은
    정책). API 키/내부 프롬프트는 절대 응답에 담지 않는다 — 이 함수는 호출 결과 텍스트만
    반환하고, 실패 시에도 프롬프트 원문이 아니라 서버 로그에만 상세를 남긴다."""
    client = OpenAI(api_key=settings.OPENAI_API_KEY, max_retries=1)
    call_count = {"n": 0}

    def llm_call(prompt: str) -> str:
        call_count["n"] += 1
        if call_count["n"] > _MAX_LLM_CALLS_PER_REQUEST:
            raise RuntimeError(
                f"[{session_id}] 프리뷰 LLM 호출 상한({_MAX_LLM_CALLS_PER_REQUEST}회) 초과 — "
                "루프 또는 재시도 폭주 의심, 중단합니다."
            )
        started = time.time()
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        elapsed = time.time() - started
        logger.info(
            "[%s] 대화형 프리뷰 LLM 호출 #%d model=%s elapsed=%.1fs usage=%s",
            session_id,
            call_count["n"],
            model,
            elapsed,
            resp.usage.model_dump() if resp.usage else None,
        )
        return resp.choices[0].message.content

    return llm_call


def _evidence_lookup_for(use_rag: bool, project_id: Optional[str]):
    if not use_rag:
        return None
    from ai.rag.orchestration.ideation_evidence_service import make_ideation_evidence_lookup

    return make_ideation_evidence_lookup(
        project_id=project_id, role_retrieval_service=_role_retrieval_service, top_k=5
    )


def _serialize_state(state: IdeationConvState) -> dict:
    """API 응답 형태로 변환한다. 실패해도 원본 예외·프롬프트·API 키는 절대 포함하지 않는다.

    용준/Claude(2026-07-21): discovery(아이디어 발굴) 모드 필드(ideation_mode/idea_candidates/
    selected_idea/selection_reason)를 추가했다 — 기존 필드는 하나도 삭제·이름 변경하지
    않았으므로(순수 추가) 기존 프론트/클라이언트는 새 필드를 무시하면 그대로 동작한다
    (요청: 기존 API 요청/응답과 최대한 하위 호환).

    용준/Claude(2026-07-21): active_stage 추가 — ideation_mode는 세션이 "최초 진입할 때"
    discovery였는지 refinement였는지만 기록하고 이후 절대 바뀌지 않는다(요청 사항 그대로
    유지). 그런데 discovery 세션도 후보를 선택한 뒤에는 refinement와 같은 흐름을 타므로,
    프론트가 배지를 정확히 표시하려면 "현재 진행 단계"가 별도로 필요하다 — active_stage가
    그 값이다(ideation_conv_state.py::active_stage_for 참고). 이 필드도 순수 추가다.

    용준/Claude(2026-07-21, 질문 주제 구조화): resolved_topics/pending_question_topic도
    순수 추가 필드다 — 기존 클라이언트는 무시하면 그대로 동작한다. state에 없으면(구버전
    세션) 각각 빈 배열/None으로 기본값을 준다. messages 안의 개별 메시지도 이제 선택적으로
    structured 필드(judgment/reason/suggestion/confirmed/unconfirmed)를 가질 수 있다 —
    content 문자열은 그대로 유지되므로 messages 자체의 필드 목록은 바뀌지 않는다(추가 키가
    각 메시지 dict 안에 하나 늘었을 뿐).

    용준/Claude(2026-07-21, /board 실 연동): original_idea_candidates/selection_intent/
    user_selection_message/source_candidates/merge_analysis도 순수 추가 필드다 —
    ideation_conv_state.py/ideation_conv_discovery.py가 이미 state에 계산해 두는 값을
    노출만 한다(새 로직 없음). /board의 결과 화면·후보 결합 컨텍스트 표시가 이 값들을
    쓴다 — conversation_context의 최근 메시지에 우연히 남아있는 것에 기대지 않고 구조화된
    필드로 직접 읽게 하기 위함이다."""
    return {
        "session_id": state["session_id"],
        "phase": state["phase"],
        "round": state["round"],
        "max_rounds": state["max_rounds"],
        # 가은/Claude(2026-07-21): /board "주제 아이디어 회의" 화면 헤더에 지금 어떤 공모전
        # 주제로 좁혀가는 중인지 보여주려고 노출한다. notice_and_criteria는 start 시점에
        # 넣어둔 값이라 세션을 이어받아(resume) 다시 그려도 그대로 유지된다 — 순수 추가 필드.
        "competition_name": (state.get("notice_and_criteria") or {}).get("competition_name", ""),
        "messages": state["messages"],
        "consensus": state["consensus"],
        "unresolved_issues": state["unresolved_issues"],
        "idea_proposal": state.get("idea_proposal"),
        "ideation_mode": state.get("ideation_mode", "refinement"),
        "active_stage": active_stage_for(state["phase"]),
        "idea_candidates": state.get("idea_candidates", []),
        "original_idea_candidates": state.get("original_idea_candidates", []),
        "selected_idea": state.get("selected_idea"),
        "selection_reason": state.get("selection_reason"),
        "resolved_topics": state.get("resolved_topics", []),
        "pending_question_topic": state.get("pending_question_topic"),
        "selection_intent": state.get("selection_intent"),
        "user_selection_message": state.get("user_selection_message"),
        "source_candidates": state.get("source_candidates", []),
        "merge_analysis": state.get("merge_analysis"),
        "error": (
            {"code": "IDEATION_CONV_NODE_FAILED", "message": f"{state.get('failed_node')} 노드에서 실패했습니다."}
            if state["phase"] == "failed"
            else None
        ),
    }


class StartRequest(BaseModel):
    competition_name: str
    competition_document: str = ""
    # 용준/Claude(2026-07-21): 요청 6번 "user_idea가 빈 문자열이어도 start API가 400을
    # 반환하지 않음" — 기본값을 빈 문자열로 두어 필드 자체를 생략해도 되게 한다(기존
    # 클라이언트가 항상 user_idea를 채워 보내던 것과 완전히 호환된다). 빈 값/공백만 있으면
    # discovery(아이디어 발굴) 모드로 시작한다 — 공모전명은 계속 필수다.
    user_idea: str = ""
    max_rounds: int = 3
    use_rag: bool = False
    project_id: Optional[str] = None
    model: str = Field(default="")  # 비워두면 settings.reviewer_model()(LLM_PROFILE 기준) 사용 — 개발용 오버라이드 허용.


class ReplyRequest(BaseModel):
    message: str
    model: str = Field(default="")


class FinalizeRequest(BaseModel):
    model: str = Field(default="")


# 가은/Claude(2026-07-21): 실측 제보 — 이 화면(board "작성 전" 흐름)이 늘 DEV_LLM_REVIEWER_
# MODEL로 고정돼 있어서, dev 프로필에 gpt-5-nano처럼 느린 추론 모델을 넣으면(파싱/JSON
# 형식 테스트용으로 dev 프로필을 그렇게 쓰는 게 팀 의도) 실제 사용자가 쓰는 이 대화형
# 회의까지 덩달아 느려졌다. 다른 LLM 호출(documents.py/meetings.py)과 똑같이
# LLM_PROFILE(dev|quality|premium)을 그대로 따르게 통일한다.
def _effective_model(requested: str) -> str:
    return requested.strip() or settings.reviewer_model()


@router.post("/start")
async def start_conversation(request: StartRequest):
    _require_preview_enabled()
    if request.use_rag and not request.project_id:
        raise HTTPException(status_code=400, detail="use_rag=true이면 project_id가 필요합니다.")

    competition_name = _clamp_text(request.competition_name, "competition_name")
    user_idea_text = _clamp_optional_text(request.user_idea, "user_idea")
    competition_document = (request.competition_document or "")[:_MAX_TEXT_LENGTH]
    effective_max_rounds = max(1, min(request.max_rounds, _MAX_ROUNDS_CAP))

    session_id = f"IDEA-CONV-{uuid.uuid4().hex[:8]}"
    notice_and_criteria = {"competition_name": competition_name, "notice_document": competition_document}
    user_idea = {"description": user_idea_text}

    llm_call = _build_llm_call(session_id, _effective_model(request.model))
    evidence_lookup = _evidence_lookup_for(request.use_rag, request.project_id)

    logger.info("[ideation-conversation] 시작 session_id=%s max_rounds=%d", session_id, effective_max_rounds)
    try:
        state = await run_in_threadpool(
            start_ideation_conversation,
            session_id=session_id,
            notice_and_criteria=notice_and_criteria,
            user_idea=user_idea,
            llm_call=llm_call,
            max_rounds=effective_max_rounds,
            evidence_lookup=evidence_lookup,
        )
    except Exception:
        logger.exception("[ideation-conversation] 시작 실패 session_id=%s", session_id)
        raise HTTPException(status_code=502, detail="대화형 회의 시작 중 오류가 발생했습니다. 서버 로그를 확인하세요.")

    _store.create(state)
    return _serialize_state(state)


@router.post("/{session_id}/reply")
async def reply_conversation(session_id: str, request: ReplyRequest):
    _require_preview_enabled()
    try:
        previous_state = _store.get(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없거나 만료되었습니다.")

    message = _clamp_text(request.message, "message")
    llm_call = _build_llm_call(session_id, _effective_model(request.model))

    try:
        state = await run_in_threadpool(
            reply_ideation_conversation,
            previous_state=previous_state,
            user_message=message,
            llm_call=llm_call,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        logger.exception("[ideation-conversation] 답변 처리 실패 session_id=%s", session_id)
        raise HTTPException(status_code=502, detail="답변 처리 중 오류가 발생했습니다. 서버 로그를 확인하세요.")

    _store.update(session_id, state)
    return _serialize_state(state)


@router.post("/{session_id}/finalize")
async def finalize_conversation(session_id: str, request: FinalizeRequest):
    _require_preview_enabled()
    try:
        previous_state = _store.get(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없거나 만료되었습니다.")

    llm_call = _build_llm_call(session_id, _effective_model(request.model))

    try:
        state = await run_in_threadpool(
            finalize_ideation_conversation,
            previous_state=previous_state,
            llm_call=llm_call,
        )
    except ValueError as exc:
        # phase != awaiting_user_decision — 요청 9~10항: 사용자가 확정 버튼을 눌러도
        # 아직 회의가 그 단계에 도달하지 않았으면 최종 종합을 거부한다.
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        logger.exception("[ideation-conversation] 최종 확정 실패 session_id=%s", session_id)
        raise HTTPException(status_code=502, detail="최종 확정 중 오류가 발생했습니다. 서버 로그를 확인하세요.")

    _store.update(session_id, state)
    return _serialize_state(state)


@router.get("/{session_id}")
async def get_conversation(session_id: str):
    _require_preview_enabled()
    try:
        state = _store.get(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없거나 만료되었습니다.")
    return _serialize_state(state)
