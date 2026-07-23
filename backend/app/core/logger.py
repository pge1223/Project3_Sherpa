import json
import logging
import re
import sys
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parents[3] / "logs"
LOG_DIR.mkdir(exist_ok=True)

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_RAG_TRACE_MARKERS = (
    "[IDEATION_EVIDENCE_",
    "[IDEATION_CLAIM_GROUNDING_",
    "[IDEATION_STRUCTURED_RESPONSE_",
    "[IDEATION_TURN_END]",
)


class RagEventFilter(logging.Filter):
    """RAG 구현 로그와 아이디어 회의의 RAG 품질 추적 이벤트만 별도 파일로 보낸다."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name.startswith("ai.rag"):
            return True
        if record.name != "ai.meeting.ideation_trace":
            return False
        message = record.getMessage()
        return any(marker in message for marker in _RAG_TRACE_MARKERS)


_SPEAKER_LABELS = {
    "planning_expert": "기획 위원",
    "dev_expert": "개발 위원",
    "ideation_facilitator": "진행자",
}


def _log_field(message: str, name: str, default: str = "-") -> str:
    quoted = re.search(rf'(?:^|\s){re.escape(name)}=("(?:\\.|[^"\\])*")', message)
    if quoted:
        try:
            return str(json.loads(quoted.group(1)))
        except (TypeError, ValueError, json.JSONDecodeError):
            return quoted.group(1).strip('"')
    plain = re.search(rf"(?:^|\s){re.escape(name)}=([^\s]+)", message)
    return plain.group(1) if plain else default


class RagDemoFormatter(logging.Formatter):
    """RAG 원본 이벤트를 데모에서 읽을 수 있는 단계별 한국어 요약으로 변환한다."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        message = record.getMessage()
        speaker = _SPEAKER_LABELS.get(_log_field(message, "speaker"), _log_field(message, "speaker"))

        if "[IDEATION_EVIDENCE_LOOKUP]" in message:
            summary = (
                f'{timestamp} [1. RAG 검색] {speaker} | 쟁점={_log_field(message, "issue")} | '
                f'검색 결과={_log_field(message, "retrieved_evidence_count")}건 | '
                f'{_log_field(message, "elapsed_ms")}ms'
            )
            return f'{summary}\n         검색어: {_log_field(message, "query")}'

        if "[IDEATION_EVIDENCE_PLAN_ACTIVE]" in message:
            valid = "통과" if _log_field(message, "validation_valid") == "true" else "실패"
            return (
                f'{timestamp} [2. Planner 선별] {speaker} | '
                f'검색 {_log_field(message, "retrieved_evidence_count")}건 → '
                f'적격 {_log_field(message, "eligible_evidence_count")}건 → '
                f'발언 주입 {_log_field(message, "injected_planned_evidence_count")}건 | '
                f'검증={valid} | 선택={_log_field(message, "selected_refs")}'
            )

        if "[IDEATION_EVIDENCE_PLAN_SHADOW_CREATED]" in message:
            return (
                f'{timestamp} [Planner 관찰] {speaker} | '
                f'검색 {_log_field(message, "retrieved_evidence_count")}건 → '
                f'적격 {_log_field(message, "eligible_evidence_count")}건 → '
                f'선택 {_log_field(message, "selected_evidence_count")}건 | '
                f'쟁점={_log_field(message, "effective_issue_title")}'
            )

        if "[IDEATION_CLAIM_GROUNDING_RESULT]" in message:
            return (
                f'{timestamp} [3. 근거 검증] {speaker} | '
                f'주장 {_log_field(message, "claim_count")}건 | '
                f'문서 근거 연결 {_log_field(message, "grounded_claim_count")}건 | '
                f'전문가 판단 {_log_field(message, "expert_judgment_count")}건 | '
                f'미지원 {_log_field(message, "unsupported_claim_count")}건 | '
                f'상태={_log_field(message, "evidence_status")}'
            )

        if "[IDEATION_TURN_END]" in message:
            summary = (
                f'{timestamp} [4. 발언 결과] {speaker} | '
                f'주입 근거={_log_field(message, "injected_evidence_count")}건 | '
                f'연결 근거={_log_field(message, "linked_evidence_count")}건 | '
                f'다음 동작={_log_field(message, "next_action")}'
            )
            text = _log_field(message, "text", "")
            return f'{summary}\n         발언: {text}' if text else summary

        if "[IDEATION_STRUCTURED_RESPONSE_" in message:
            return f"{timestamp} [응답 검증] {message}"
        if "[IDEATION_CLAIM_GROUNDING_START]" in message:
            return (
                f'{timestamp} [근거 검증 시작] {speaker} | '
                f'주장={_log_field(message, "claim_count")}건 | '
                f'주입 근거={_log_field(message, "injected_evidence_count")}건'
            )
        if message.startswith("[IDEATION_EVIDENCE_"):
            return f"{timestamp} [근거 처리] {message}"

        component = record.name.removeprefix("ai.rag.") or "rag"
        return f"{timestamp} [RAG 내부/{component}] {message}"


class MinuteBucketFileHandler(logging.Handler):
    """로그 발생 시각의 달력상 분을 파일명으로 사용해 실시간 기록하는 핸들러.

    예: 2026-07-23 10:42:37 이벤트는 rag_analyzer_20260723_1042.txt에 기록된다.
    다음 분의 첫 이벤트가 들어오면 기존 stream을 닫고 새 파일을 연다. 빈 분에는 파일을
    만들지 않으며 매 emit마다 flush해 데모 중에도 파일 내용을 즉시 확인할 수 있다.
    """

    terminator = "\n"

    def __init__(self, directory: str | Path, prefix: str, *, encoding: str = "utf-8") -> None:
        super().__init__()
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.prefix = prefix
        self.encoding = encoding
        self._bucket: str | None = None
        self._stream = None

    def _ensure_stream(self, record: logging.LogRecord) -> None:
        bucket = datetime.fromtimestamp(record.created).strftime("%Y%m%d_%H%M")
        if bucket == self._bucket and self._stream is not None:
            return
        if self._stream is not None:
            self._stream.close()
        path = self.directory / f"{self.prefix}_{bucket}.txt"
        self._stream = path.open("a", encoding=self.encoding)
        if path.stat().st_size == 0:
            minute = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M")
            self._stream.write(
                "AI Review Board RAG 실시간 분석 로그\n"
                f"기록 구간: {minute} (1분 단위)\n"
                "흐름: RAG 검색 → Planner 근거 선별 → 주장·근거 검증 → 전문가 발언\n\n"
            )
            self._stream.flush()
        self._bucket = bucket

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._ensure_stream(record)
            self._stream.write(self.format(record) + self.terminator)
            self._stream.flush()
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        try:
            if self._stream is not None:
                self._stream.close()
                self._stream = None
        finally:
            super().close()


def setup_logger() -> logging.Logger:
    logger = logging.getLogger("review_board")
    logger.setLevel(logging.INFO)

    if logger.handlers:
        return logger

    # 가은/Claude(2026-07-18): Windows 콘솔의 기본 인코딩(cp949)이 em dash(—) 등 일부
    # 유니코드 문자를 못 받아서, 그런 문자가 포함된 로그가 뜨는 순간
    # UnicodeEncodeError로 로깅 자체가 깨지는 걸 실측(백엔드 터미널에서 "--- Logging
    # error ---"만 찍히고 정작 로그 내용은 안 보임)했다. 로그 메시지마다 특수문자를
    # 피해 다니는 대신, stdout 자체를 UTF-8로 재설정해서 근본적으로 막는다
    # (reconfigure는 실제 콘솔 스트림에서만 되고 테스트 등에서 stdout이 캡처돼 있으면
    # 없을 수 있어 hasattr로 방어).
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (ValueError, OSError):
            pass

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))

    file_handler = TimedRotatingFileHandler(
        filename=LOG_DIR / "app.log",
        when="midnight",
        interval=1,
        backupCount=7,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    file_handler.suffix = "%Y-%m-%d"

    # RAG 데모·품질 분석용 실시간 분 단위 로그. app.log를 대체하지 않고 같은 이벤트를
    # rag_analyzer_YYYYMMDD_HHmm.txt에도 기록한다. RAG 이벤트가 없는 분에는 빈 파일을
    # 생성하지 않는다.
    rag_minute_handler = MinuteBucketFileHandler(LOG_DIR, "rag_analyzer")
    rag_minute_handler.setLevel(logging.INFO)
    rag_minute_handler.setFormatter(RagDemoFormatter())
    rag_minute_handler.addFilter(RagEventFilter())

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    for uvicorn_logger_name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        uv_logger = logging.getLogger(uvicorn_logger_name)
        uv_logger.handlers = []
        uv_logger.addHandler(console_handler)
        uv_logger.addHandler(file_handler)

    # 가은/Claude(2026-07-18): 이 함수는 "review_board"라는 이름의 로거에만 핸들러를
    # 붙이는데, meetings.py/documents.py 등 나머지 라우트 파일은 전부
    # logging.getLogger(__name__)(예: "app.api.routes.meetings")을 쓴다 — 이 로거들엔
    # 핸들러가 없고, 부모로 propagate해도 root까지 핸들러가 하나도 없어서 INFO 로그가
    # 전부 조용히 사라지고 있었다(실측: /ask의 LLM 호출 로그, rubric/evidence 진단 로그
    # 전부 터미널에 한 줄도 안 찍힘). backend/app 아래 모든 모듈 이름이 "app."으로
    # 시작하므로, "app" 로거 하나에만 핸들러를 붙이면 자식 로거들이 propagate로 전부
    # 받는다 — 파일마다 import를 바꿀 필요 없이 한 곳만 고치면 된다.
    # 가은/Claude(2026-07-18): 같은 이유로 ai/rag, ai/meeting 쪽 모듈(예:
    # ai.rag.orchestration.meeting_evidence_service)도 전부 logging.getLogger(__name__)이라
    # "ai."로 시작한다 — "app" 로거만 고치면 이쪽(RAG-003~005 근거 검색 실패 시
    # logger.exception() 등)은 여전히 안 보인다. 같은 핸들러를 "ai" 로거에도 붙인다.
    for namespace in ("app", "ai"):
        ns_logger = logging.getLogger(namespace)
        ns_logger.setLevel(logging.INFO)
        if not ns_logger.handlers:
            ns_logger.addHandler(console_handler)
            ns_logger.addHandler(file_handler)
            if namespace == "ai":
                ns_logger.addHandler(rag_minute_handler)

    return logger


logger = setup_logger()
