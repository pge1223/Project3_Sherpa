"""
Unit Tests for ai.rag.retrieval.diagnostics.StageWatchdog
=============================================================
2026-07-18 PR 리뷰 지적사항 대응: faulthandler.dump_traceback(file=io.StringIO())가
UnsupportedOperation("fileno")로 실패하던 버그를 tempfile.TemporaryFile()로 고친 뒤,
threshold를 짧게 설정해 실제로 watchdog 콜백이 동작하고 스택 덤프가 로그에 남는지
검증한다 (이전에는 예외가 타이머 스레드 안에서 조용히 삼켜져 로그 자체가 비어 있었다).
"""

import logging
import time

from ai.rag.retrieval.diagnostics import StageWatchdog


def test_watchdog_fires_and_logs_stack_dump_when_stage_exceeds_threshold(caplog):
    with caplog.at_level(logging.WARNING, logger="ai.rag.retrieval.diagnostics"):
        with StageWatchdog("embed", "doc-1", threshold_seconds=0.05):
            time.sleep(0.3)

    stuck_records = [r for r in caplog.records if "rag.indexing.stage_stuck" in r.message]
    assert stuck_records, "threshold를 넘겼는데 stage_stuck 로그가 남지 않았다"

    record = stuck_records[0]
    assert "stage=embed" in record.message
    assert "document_id=doc-1" in record.message
    # faulthandler.dump_traceback(all_threads=True)의 실제 출력 형식 확인
    assert "Current thread" in record.message or "Thread" in record.message


def test_watchdog_does_not_log_when_stage_finishes_before_threshold(caplog):
    with caplog.at_level(logging.WARNING, logger="ai.rag.retrieval.diagnostics"):
        with StageWatchdog("embed", "doc-2", threshold_seconds=5.0):
            pass
        # 타이머가 확실히 취소됐는지 확인하기 위해 threshold보다 짧게만 대기
        time.sleep(0.1)

    stuck_records = [r for r in caplog.records if "rag.indexing.stage_stuck" in r.message]
    assert not stuck_records, "정상 종료된 stage인데 stage_stuck 로그가 남았다"


def test_watchdog_dump_stacks_does_not_raise_unsupportedoperation():
    """io.StringIO() 시절 재현되던 UnsupportedOperation('fileno')이 더 이상 나지 않는지
    직접 호출해 확인한다 (with 블록 타이머 경유가 아니라 메서드를 바로 호출)."""
    watchdog = StageWatchdog("embed", "doc-3", threshold_seconds=999)
    watchdog._dump_stacks()  # 예외 없이 끝나야 한다
