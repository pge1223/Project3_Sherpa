import logging

from app.api.routes.ideation_conversation_preview import (
    _trace_evidence_lookup,
    configure_ideation_trace,
)


def test_rag_trace_logs_call_and_sources_before_expert_generation(caplog):
    calls = []

    def lookup(persona_id, query):
        calls.append((persona_id, query))
        return [
            {
                "document_name": "공고문.pdf",
                "chunk_id": "chunk-1",
                "page": 3,
                "score": 0.91,
                "text": "로그에 남기지 않을 원문",
            }
        ]

    configure_ideation_trace(enabled=True, content_max_chars=500, stream_deltas=False)
    try:
        traced = _trace_evidence_lookup(lookup, project_id="project-1", top_k=5)
        with caplog.at_level(logging.INFO, logger="ai.meeting.ideation_trace"):
            result = traced("planning_expert", "평가 기준에 맞는 아이디어")
    finally:
        configure_ideation_trace(enabled=None, content_max_chars=None, stream_deltas=None)

    rendered = "\n".join(record.getMessage() for record in caplog.records)
    assert calls == [("planning_expert", "평가 기준에 맞는 아이디어")]
    assert result[0]["chunk_id"] == "chunk-1"
    assert "[IDEATION_RAG_SEARCH_START]" in rendered
    assert 'speaker_name="기획 위원"' in rendered
    assert 'timing="전문가 발언 생성 전"' in rendered
    assert "[IDEATION_RAG_SEARCH_COMPLETE]" in rendered
    assert 'result_count=1' in rendered
    assert '"document":"공고문.pdf"' in rendered
    assert '"chunk_id":"chunk-1"' in rendered
    assert "로그에 남기지 않을 원문" not in rendered


def test_rag_trace_identifies_development_role(caplog):
    configure_ideation_trace(enabled=True, content_max_chars=500, stream_deltas=False)
    try:
        traced = _trace_evidence_lookup(lambda *_: [], project_id="project-1", top_k=5)
        with caplog.at_level(logging.INFO, logger="ai.meeting.ideation_trace"):
            traced("dev_expert", "구현 가능성")
    finally:
        configure_ideation_trace(enabled=None, content_max_chars=None, stream_deltas=None)

    rendered = "\n".join(record.getMessage() for record in caplog.records)
    assert 'speaker_name="개발 위원"' in rendered
    assert 'role="technology"' in rendered
    assert 'result_count=0' in rendered
