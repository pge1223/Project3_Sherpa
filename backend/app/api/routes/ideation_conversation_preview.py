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

import asyncio
import json
import logging
import queue
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
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
# 용준/Claude(2026-07-21, 요청: 실시간 스트리밍) — 스트리밍 llm_call 생성 로직은 별도
# 모듈(ideation_conversation_streaming.py)로 분리했다(FastAPI/OpenAI 클라이언트 배선은
# 이 파일이, "프롬프트를 보고 어떻게 스트리밍할지 결정"하는 순수 로직은 그 모듈이 맡는다
# — 순수 로직 쪽이 실제 OpenAI 없이도 유닛 테스트가 가능해야 하기 때문이다).
from app.api.routes.ideation_conversation_streaming import make_streaming_llm_call  # noqa: E402

# ---------------------------------------------------------------------------
# 안전장치 상한값 (요청 "개발용 API" 절)
# ---------------------------------------------------------------------------
_SESSION_TTL_SECONDS = 30 * 60  # 30분 이상 응답 없는 세션은 만료된 것으로 간주한다.
_MAX_SESSIONS = 200  # 이 이상이면 가장 오래전에 활동한 세션부터 제거한다(메모리 상한).
_MAX_ROUNDS_CAP = 3  # 요청 max_rounds가 이보다 크면 잘라낸다.
_MAX_TEXT_LENGTH = 2000  # 공모전 설명/아이디어/답변 1건당 최대 길이(문자 수).
# 용준/Claude(2026-07-21, 요청: 위원 간 실제 회의로 개편) — expert_discussion 라운드가
# sufficiency(1) + planning_position(1) + dev_review(1) + [선택적] planning_revision(1) +
# discussion_facilitator(1) + [continue_round이면] 다음 planning_question(1) = 최대 6회
# 호출로 늘었고, 각 구조화 호출은 재시도 1회까지 더 셀 수 있어(_safe_call_structured_json)
# 여유를 넉넉히 둔다.
# 가은/Claude(2026-07-22, 요청: 아이디어 기획 캔버스 자동 갱신 — 경이 협의 완료) — 매 라운드
# 끝에 canvas_update 호출이 1회(재시도 시 2회) 추가됐고, continue_round로 한 요청 안에서
# 라운드가 두 번 돌면 최대 +4회까지 늘 수 있어 상한을 12 -> 16으로 올린다(상한의 목적은
# 정확한 예산이 아니라 루프/재시도 폭주 감지다 — 기존 정책 그대로).
_MAX_LLM_CALLS_PER_REQUEST = 16  # 한 HTTP 요청에서 허용하는 최대 LLM 호출 수(재시도 포함 여유).


class _SessionRecord:
    __slots__ = ("state", "created_at", "last_active_at", "busy_lock")

    def __init__(self, state: IdeationConvState):
        self.state = state
        now = time.time()
        self.created_at = now
        self.last_active_at = now
        # 용준/Claude(2026-07-21, 요청: 세션 안정성) — 같은 session_id에 동시에 여러
        # reply/finalize 요청이 들어오면(사용자가 전송 버튼을 연타하거나 중복 탭을 열어도)
        # 그래프가 같은 previous_state를 동시에 두 번 진행시켜 메시지가 뒤섞이거나
        # candidate_regeneration_count 같은 카운터가 잘못 갱신될 수 있다. 세션마다 락 하나로
        # "지금 이 세션을 처리 중인 요청이 있는지"만 표시한다(전역 락이 아니라 세션별이라
        # 서로 다른 세션의 요청은 완전히 병렬로 처리된다).
        self.busy_lock = threading.Lock()


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

    def try_acquire(self, session_id: str) -> _SessionRecord | None:
        """이 세션을 지금 처리해도 되면 레코드를 반환하고 락을 잡는다. 세션이 없으면
        None, 이미 다른 요청이 처리 중이면(락이 이미 잡혀 있으면) 별도 예외
        (_SessionBusyError)를 던진다 — "세션 없음"과 "세션 사용 중"을 호출부가 다른 HTTP
        상태 코드(404 vs 409)로 구분해야 하기 때문이다. 성공하면 반드시
        release(session_id)를 호출해야 한다(finally 블록에서)."""
        with self._lock:
            self._sweep_expired_locked()
            record = self._sessions.get(session_id)
        if record is None:
            return None
        if not record.busy_lock.acquire(blocking=False):
            raise _SessionBusyError(session_id)
        return record

    def release(self, session_id: str) -> None:
        with self._lock:
            record = self._sessions.get(session_id)
        if record is not None:
            try:
                record.busy_lock.release()
            except RuntimeError:
                pass  # 이미 풀려 있으면(방어적) 조용히 무시한다.


class _SessionBusyError(Exception):
    """요청 1건이 이미 이 세션을 처리 중일 때(동시 reply/finalize 방지) 던진다."""

    def __init__(self, session_id: str):
        super().__init__(session_id)
        self.session_id = session_id


_store = _SessionStore(_SESSION_TTL_SECONDS, _MAX_SESSIONS)


def _require_preview_enabled() -> None:
    if not settings.ENABLE_IDEATION_PREVIEW:
        raise HTTPException(status_code=404, detail="Not Found")


def _require_streaming_enabled() -> None:
    if not settings.ENABLE_IDEATION_STREAMING:
        raise HTTPException(status_code=404, detail="Not Found")


def _acquire_session_or_404(session_id: str) -> IdeationConvState:
    """이 세션을 지금 처리해도 되면 previous_state를 반환하고 세션 락을 잡는다(호출부가
    반드시 finally에서 _store.release(session_id)를 불러야 한다). 세션이 없으면 404,
    이미 다른 요청이 처리 중이면 _SessionBusyError를 그대로 전파한다(호출부가 409로
    변환한다)."""
    record = _store.try_acquire(session_id)
    if record is None:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없거나 만료되었습니다.")
    return record.state


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


def _build_streaming_backends(session_id: str, model: str):
    """실제 OpenAI 클라이언트를 감싸 make_streaming_llm_call()이 기대하는 두 콜백을
    만든다 — stream_chat_completion(prompt)는 원문 텍스트 조각을 순서대로 만들어내는
    제너레이터(OpenAI stream=True), call_chat_completion(prompt)은 기존 _build_llm_call과
    동일한 블로킹 호출(스트리밍 대상이 아닌 분류·후보 생성 등에 쓴다). 호출 횟수 상한은
    make_streaming_llm_call이 중앙에서 관리하므로 여기서는 세지 않는다."""
    client = OpenAI(api_key=settings.OPENAI_API_KEY, max_retries=1)

    def stream_chat_completion(prompt: str):
        started = time.time()
        stream = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            stream=True,
        )
        try:
            for chunk in stream:
                if not chunk.choices:
                    continue
                text = getattr(chunk.choices[0].delta, "content", None)
                if text:
                    yield text
        finally:
            logger.info(
                "[%s] 대화형 프리뷰 스트리밍 LLM 호출 model=%s elapsed=%.1fs", session_id, model, time.time() - started
            )

    def call_chat_completion(prompt: str) -> str:
        started = time.time()
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        logger.info(
            "[%s] 대화형 프리뷰 LLM 호출(비-스트리밍 구간) model=%s elapsed=%.1fs",
            session_id,
            model,
            time.time() - started,
        )
        return resp.choices[0].message.content

    return stream_chat_completion, call_chat_completion


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
        # 용준/Claude(2026-07-21, 요청: 위원 간 실제 회의로 개편) — 순수 추가 필드. 기존
        # 클라이언트는 무시하면 그대로 동작한다. 구버전 세션(discussion_rounds 키가 없는
        # state)에는 빈 배열을 기본값으로 준다.
        "discussion_rounds": state.get("discussion_rounds", []),
        # 가은/Claude(2026-07-22, 요청: 아이디어 기획 캔버스 자동 갱신 — 경이 협의 완료) —
        # 순수 추가 필드. 매 라운드 canvas_update 노드가 갱신하는 기획 캔버스 값(키 이름은
        # selected_idea와 동일). 프론트(IdeaCanvasPanel.jsx)는 idea_canvas가 없으면
        # selected_idea로 폴백해 그린다. 구버전 세션 state에는 키가 없을 수 있다.
        "idea_canvas": state.get("idea_canvas"),
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
        previous_state = _acquire_session_or_404(session_id)
    except _SessionBusyError:
        raise HTTPException(status_code=409, detail="이 세션은 이미 다른 요청을 처리하고 있습니다.")

    try:
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
    finally:
        _store.release(session_id)


# NDJSON 스트림 소비자(비동기 이벤트 제너레이터)가 "이 스트림이 끝났다"를 판별하는 데
# 쓰는 내부 전용 sentinel — 실제 이벤트 dict와 절대 혼동되지 않도록 object() 그대로 쓴다.
_STREAM_DONE_SENTINEL = object()
# 클라이언트 연결 종료 여부를 이 주기(초)로 재확인한다 — 그동안 새 이벤트가 없어도
# event_queue.get(timeout=...)이 이 시간 뒤에 깨어나 disconnect 체크로 돌아온다(요청:
# "클라이언트 연결 종료 시 가능한 범위에서 LLM 스트림 정리").
_DISCONNECT_POLL_SECONDS = 1.0


@router.post("/{session_id}/reply/stream")
async def reply_conversation_stream(session_id: str, request: ReplyRequest, http_request: Request):
    """POST /reply와 같은 일(사용자 답변 반영)을 하지만, 응답을 한 번에 돌려주는 대신
    NDJSON(application/x-ndjson) 한 줄마다 이벤트 하나씩 흘려보낸다 — 사용자에게 보이는
    메시지를 만드는 LLM 호출은 실제 OpenAI 토큰이 도착하는 즉시 message_delta로 나간다
    (가짜 타이핑 효과 아님, ideation_conversation_streaming.py::make_streaming_llm_call 참고).

    그래프 실행(reply_ideation_conversation)은 동기 함수라 별도 스레드에서 돌리고, 그
    스레드가 sink()로 큐에 넣는 이벤트를 이 async 제너레이터가 꺼내 그대로 클라이언트에게
    전달하는 "생산자(스레드)-소비자(이벤트 루프)" 패턴을 쓴다. 세션 state는 그래프 실행이
    끝까지 성공했을 때만(canonical state) _store에 저장한다 — 스트리밍 중 클라이언트
    연결이 끊겨도 워커 스레드는 계속 실행되어 정상적으로 state를 저장한다(요청: "스트리밍
    중 연결이 끊겨도 세션 state가 손상되지 않음")."""
    _require_preview_enabled()
    _require_streaming_enabled()
    message = _clamp_text(request.message, "message")

    try:
        previous_state = _acquire_session_or_404(session_id)
    except _SessionBusyError:
        raise HTTPException(status_code=409, detail="이 세션은 이미 다른 요청을 처리하고 있습니다.")

    model = _effective_model(request.model)
    event_queue: "queue.Queue[object]" = queue.Queue()

    def sink(event: dict) -> None:
        event_queue.put(event)

    def worker() -> None:
        try:
            stream_chat_completion, call_chat_completion = _build_streaming_backends(session_id, model)
            llm_call = make_streaming_llm_call(
                session_id,
                sink,
                stream_chat_completion=stream_chat_completion,
                call_chat_completion=call_chat_completion,
                max_calls=_MAX_LLM_CALLS_PER_REQUEST,
            )
            state = reply_ideation_conversation(
                previous_state=previous_state,
                user_message=message,
                llm_call=llm_call,
            )
            _store.update(session_id, state)
            sink({"type": "state", "state": _serialize_state(state)})
        except ValueError as exc:
            sink({"type": "error", "code": "invalid_request", "message": str(exc)})
        except Exception:
            logger.exception("[ideation-conversation] 스트리밍 답변 처리 실패 session_id=%s", session_id)
            sink(
                {
                    "type": "error",
                    "code": "llm_failure",
                    "message": "답변 처리 중 오류가 발생했습니다. 서버 로그를 확인하세요.",
                }
            )
        finally:
            _store.release(session_id)
            event_queue.put(_STREAM_DONE_SENTINEL)

    threading.Thread(target=worker, daemon=True).start()

    def _get_next_event() -> object:
        try:
            return event_queue.get(timeout=_DISCONNECT_POLL_SECONDS)
        except queue.Empty:
            return None  # 타임아웃 — 아직 다음 이벤트가 없다(정상, disconnect 재확인용).

    async def event_generator():
        loop = asyncio.get_event_loop()
        while True:
            if await http_request.is_disconnected():
                break
            item = await loop.run_in_executor(None, _get_next_event)
            if item is None:
                continue
            if item is _STREAM_DONE_SENTINEL:
                break
            yield (json.dumps(item, ensure_ascii=False) + "\n").encode("utf-8")

    return StreamingResponse(event_generator(), media_type="application/x-ndjson; charset=utf-8")


@router.post("/{session_id}/finalize")
async def finalize_conversation(session_id: str, request: FinalizeRequest):
    _require_preview_enabled()
    try:
        previous_state = _acquire_session_or_404(session_id)
    except _SessionBusyError:
        raise HTTPException(status_code=409, detail="이 세션은 이미 다른 요청을 처리하고 있습니다.")

    try:
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
    finally:
        _store.release(session_id)


@router.get("/{session_id}")
async def get_conversation(session_id: str):
    _require_preview_enabled()
    try:
        state = _store.get(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없거나 만료되었습니다.")
    return _serialize_state(state)
