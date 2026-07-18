"""
Stage Watchdog — hang 진단용 보조 유틸
=========================================
2026-07-18, fetch-url 색인이 project_id가 있을 때만 5분 이상 멈추는 버그 조사(용준/Claude)
중 도입. 원인은 CPU 사용률이 거의 0에 가까운 "블로킹"이라 일반 예외 로깅으로는 잡히지
않는다 — 그렇다고 asyncio.wait_for()로 감싸 타임아웃 응답만 주는 건 근본 해결이 아니다
(블로킹된 스레드와 그 스레드가 들고 있는 락/리소스는 그대로 남는다, 스코프 문서 참고).

StageWatchdog는 요청을 취소하지 않는다 — 지정한 시간 안에 with 블록이 끝나지 않으면
daemon 타이머 스레드가 그 시점의 전체 스레드 스택을 로그에 남길 뿐이다. 정상 종료되면
아무 로그도 남기지 않고 타이머만 취소한다. 다음에 같은 hang이 재발하면, 어느 스레드가
어느 코드 줄에서 멈춰 있는지 로그만 보고 바로 알 수 있게 하는 것이 목적이다.
"""

import faulthandler
import logging
import tempfile
import threading

logger = logging.getLogger(__name__)


class StageWatchdog:
    """
    사용례:
        with StageWatchdog("embed", document_id, threshold_seconds=30):
            embedder.embed_chunking_result(...)

    threshold_seconds 안에 with 블록을 빠져나가지 못하면 WARNING 레벨로
    "rag.indexing.stage_stuck" 로그 한 줄 + 전체 스레드 스택 덤프를 남긴다.
    """

    def __init__(self, stage: str, document_id: str, threshold_seconds: float = 30.0):
        self._stage = stage
        self._document_id = document_id
        self._threshold = threshold_seconds
        self._timer: threading.Timer | None = None

    def __enter__(self) -> "StageWatchdog":
        self._timer = threading.Timer(self._threshold, self._dump_stacks)
        self._timer.daemon = True
        self._timer.start()
        return self

    def _dump_stacks(self) -> None:
        # faulthandler.dump_traceback()은 C 레벨에서 실제 OS 파일 디스크립터(fileno())에
        # 직접 쓴다 — io.StringIO()는 fileno()가 없어 UnsupportedOperation을 낸다(실측 확인).
        # tempfile.TemporaryFile()로 진짜 파일을 열어 쓰고 다시 읽어 로그에 담는다.
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as f:
            faulthandler.dump_traceback(file=f, all_threads=True)
            f.seek(0)
            stacks = f.read()
        logger.warning(
            "rag.indexing.stage_stuck stage=%s document_id=%s threshold_s=%.0f\n%s",
            self._stage,
            self._document_id,
            self._threshold,
            stacks,
        )

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self._timer is not None:
            self._timer.cancel()
        return False
