import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parents[3] / "logs"
LOG_DIR.mkdir(exist_ok=True)

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


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

    return logger


logger = setup_logger()
