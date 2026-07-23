from openai import OpenAI

from app.config import settings


def trace_openai_client(client: OpenAI) -> OpenAI:
    """가은/Claude(2026-07-23, 요청: LangSmith 트레이싱 연결) — documents.py/meetings.py/
    workbench.py/ideation_*.py가 만드는 OpenAI 클라이언트를 settings.LANGSMITH_TRACING이
    켜져 있을 때만 langsmith.wrap_openai로 감싼다. 클라이언트 생성 자체(`OpenAI(...)`)는
    각 라우트 파일에 그대로 남겨둔다 — 테스트들이 `monkeypatch.setattr(route_module,
    "OpenAI", FakeOpenAI)`로 그 심볼을 직접 가짜로 바꿔치기하므로, 여기서 생성까지
    가져오면 그 패치가 조용히 무력화된다. 꺼져 있으면(기본값) 입력 client를 그대로
    반환한다 — 기존 동작과 100% 동일.
    """
    if settings.LANGSMITH_TRACING:
        from langsmith.wrappers import wrap_openai

        return wrap_openai(client)
    return client
