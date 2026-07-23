import logging
import sys
from datetime import datetime, timedelta
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parents[3] / "logs"
LOG_DIR.mkdir(exist_ok=True)

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class _MinuteTimestampedFileHandler(logging.Handler):
    """가은/Claude(2026-07-23, 요청: 데모 파이프라인 점검용 전용 로그) — 표준
    TimedRotatingFileHandler는 "현재 활성 파일"의 이름을 생성 시점 그대로 고정해두고 지난
    파일만 타임스탬프를 붙여 옆으로 치운다. 여기서는 반대로 "지금 보고 있는 파일 이름
    자체"가 항상 그 파일이 열린 시각을 담고 있어야 한다는 요청이라, 매 emit()마다 마지막
    파일을 연 지 1분이 지났는지 검사해서 지났으면 새 타임스탬프로 새 파일을 연다. 로그가
    없는 동안(비활성 구간)은 새 파일을 만들지 않는다 — 첫 emit()이 열 때만 생성된다."""

    def __init__(self, log_dir: Path, prefix: str, rotate_interval: timedelta, encoding: str = "utf-8"):
        super().__init__()
        self._log_dir = log_dir
        self._prefix = prefix
        self._rotate_interval = rotate_interval
        self._encoding = encoding
        self._stream = None
        self._opened_at: datetime | None = None

    def _needs_new_file(self) -> bool:
        return self._stream is None or (datetime.now() - self._opened_at) >= self._rotate_interval

    def _open_new_file(self) -> None:
        if self._stream is not None:
            try:
                self._stream.close()
            except Exception:
                pass
        now = datetime.now()
        self._opened_at = now
        filename = self._log_dir / f"{self._prefix}_{now.strftime('%Y%m%d%H%M%S')}.txt"
        self._stream = open(filename, "a", encoding=self._encoding)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            with self.lock:
                if self._needs_new_file():
                    self._open_new_file()
                self._stream.write(self.format(record) + "\n")
                self._stream.flush()
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        with self.lock:
            if self._stream is not None:
                try:
                    self._stream.close()
                finally:
                    self._stream = None
        super().close()


class _UrlPdfAnalyzerFilter(logging.Filter):
    """가은/Claude(2026-07-23): "1번(URL 분석 및 업로드된 파일 분석) 파이프라인" 범위만
    고른다 — ai/rag/parsers, ai/rag/loaders 쪽 로거이거나(파일 파싱/OCR/문서 추출),
    documents.py의 fetch-url/upload 색인 로그([fetch-url]/[upload] 접두사, 기존 컨벤션)만
    통과시킨다. 회의 진행·RAG 검색 등 다른 구간 로그는 이 파일에 섞이지 않는다."""

    _LOGGER_PREFIXES = ("ai.rag.parsers", "ai.rag.loaders")
    _MESSAGE_PREFIXES = ("[fetch-url]", "[upload]")

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name.startswith(self._LOGGER_PREFIXES):
            return True
        return record.getMessage().startswith(self._MESSAGE_PREFIXES)


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

    # 가은/Claude(2026-07-23, 요청: 데모 파이프라인 점검용 — 1번 URL/파일 분석 전용 로그):
    # 기존 콘솔/logs/app.log는 그대로 두고(전체 백엔드 공용), 이 구간만 따로 잘라볼 수 있게
    # logs/url_pdf_analyzer_<생성시각>.txt를 1분 단위로 새로 만들며 병행 기록한다. root
    # 로거에 한 번만 붙이면 "app"/"ai" 하위 모든 로거의 레코드가 propagate로 여기까지
    # 오므로(각 로거의 level은 emit 시점에 한 번만 검사되고, 이후 부모 전파 단계에서는
    # 핸들러 자체의 필터만 적용된다), 필터로 범위를 좁히는 쪽이 여러 로거에 개별
    # 부착하는 것보다 안전하다 — 새 area-1 모듈이 추가돼도 필터 프리픽스만 늘리면 된다.
    root_logger = logging.getLogger()
    if not any(isinstance(h, _MinuteTimestampedFileHandler) for h in root_logger.handlers):
        url_pdf_handler = _MinuteTimestampedFileHandler(
            LOG_DIR, prefix="url_pdf_analyzer", rotate_interval=timedelta(minutes=1), encoding="utf-8",
        )
        url_pdf_handler.setLevel(logging.INFO)
        url_pdf_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
        url_pdf_handler.addFilter(_UrlPdfAnalyzerFilter())
        root_logger.addHandler(url_pdf_handler)

    return logger


logger = setup_logger()
