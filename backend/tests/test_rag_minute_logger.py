from __future__ import annotations

import logging
from datetime import datetime

from app.core.logger import MinuteBucketFileHandler, RagDemoFormatter, RagEventFilter


def _record(name: str, message: str, at: datetime) -> logging.LogRecord:
    record = logging.LogRecord(name, logging.INFO, __file__, 1, message, (), None)
    record.created = at.timestamp()
    return record


def test_minute_handler_writes_and_flushes_into_calendar_minute_files(tmp_path):
    handler = MinuteBucketFileHandler(tmp_path, "rag_analyzer")
    handler.setFormatter(RagDemoFormatter())

    first = _record("ai.rag.search", "[RAG_SEARCH] first", datetime(2026, 7, 23, 10, 42, 37))
    second = _record("ai.rag.search", "[RAG_SEARCH] second", datetime(2026, 7, 23, 10, 43, 1))
    handler.emit(first)
    handler.emit(second)
    handler.close()

    first_file = tmp_path / "rag_analyzer_20260723_1042.txt"
    second_file = tmp_path / "rag_analyzer_20260723_1043.txt"
    first_text = first_file.read_text(encoding="utf-8")
    second_text = second_file.read_text(encoding="utf-8")
    assert "AI Review Board RAG 실시간 분석 로그" in first_text
    assert "기록 구간: 2026-07-23 10:42" in first_text
    assert "[RAG 내부/search] [RAG_SEARCH] first" in first_text
    assert "기록 구간: 2026-07-23 10:43" in second_text
    assert "[RAG 내부/search] [RAG_SEARCH] second" in second_text


def test_rag_filter_keeps_rag_and_relevant_ideation_trace_only():
    event_filter = RagEventFilter()
    at = datetime(2026, 7, 23, 10, 42, 37)

    assert event_filter.filter(_record("ai.rag.orchestration", "search complete", at)) is True
    assert event_filter.filter(
        _record("ai.meeting.ideation_trace", "[IDEATION_EVIDENCE_PLAN_ACTIVE] selected=2", at)
    ) is True
    assert event_filter.filter(
        _record("ai.meeting.ideation_trace", "[IDEATION_TURN_START] speaker=planning", at)
    ) is False
    assert event_filter.filter(_record("app.api.routes.projects", "project loaded", at)) is False


def test_demo_formatter_summarizes_retrieval_planner_grounding_and_turn():
    formatter = RagDemoFormatter()
    at = datetime(2026, 7, 23, 10, 42, 37)
    messages = [
        '[IDEATION_EVIDENCE_LOOKUP] speaker="planning_expert" issue="problem" '
        'query="스마트 에너지" retrieved_evidence_count=5 elapsed_ms=575.7',
        '[IDEATION_EVIDENCE_PLAN_ACTIVE] speaker="planning_expert" retrieved_evidence_count=5 '
        'eligible_evidence_count=4 injected_planned_evidence_count=2 validation_valid=true '
        'selected_refs=["E4","E1"]',
        '[IDEATION_CLAIM_GROUNDING_RESULT] speaker="planning_expert" claim_count=2 '
        'grounded_claim_count=1 expert_judgment_count=1 unsupported_claim_count=0 '
        'evidence_status="grounded"',
        '[IDEATION_TURN_END] speaker="planning_expert" injected_evidence_count=2 '
        'linked_evidence_count=1 next_action="continue_discussion" text="근거 기반 발언"',
    ]

    rendered = "\n".join(
        formatter.format(_record("ai.meeting.ideation_trace", message, at)) for message in messages
    )

    assert "[1. RAG 검색] 기획 위원" in rendered
    assert "검색 5건 → 적격 4건 → 발언 주입 2건" in rendered
    assert "문서 근거 연결 1건" in rendered
    assert "발언: 근거 기반 발언" in rendered
