# 작성자: 경이
# 목적: LangGraph 노드가 사용하는 LLM 호출 인터페이스와 JSON 파싱 유틸(M4). 실제 API
#       연동은 이 시그니처(str -> str)를 구현하는 함수를 넣기만 하면 되도록 인터페이스만
#       분리해 둔다. 테스트에서는 고정 응답을 돌려주는 stub 함수를 쓴다.
#       make_openai_llm_call의 모델명은 일부러 기본값을 두지 않는다 — 실제 사용 모델은
#       가은이 비용/품질 검토 중이라, 값을 호출부(엔트리포인트/설정)가 명시하게 강제한다.
# import: 표준 라이브러리 json, typing. openai 패키지는 make_openai_llm_call 내부에서
#         지연 import(다른 노드/테스트는 openai 설치 없이도 동작해야 하므로).

from __future__ import annotations

import json
from typing import Any, Callable

LLMCall = Callable[[str], str]


def parse_json_response(text: str) -> dict:
    """LLM 응답 문자열에서 JSON 객체를 파싱한다.

    프롬프트는 마크다운 코드블록 없이 JSON만 반환하라고 지시하지만, 실제 LLM은 종종
    ```json ... ``` 로 감싸 응답하거나("코드블록") "물론이죠! ... {..} ... 도움이 되었길
    바랍니다" 처럼 JSON 앞뒤에 설명 문장을 덧붙이기도 한다("전후 설명문"). 코드블록은
    벗겨내고, 그래도 파싱이 안 되면 문자열에서 첫 '{'부터 마지막 '}'까지만 잘라 한 번 더
    시도한다 — 두 시도 모두 실패하면 예외를 그대로 올려 호출부(_safe_call_json)가 재시도/
    폴백 정책을 적용하게 한다(여기서 조용히 빈 dict를 반환하지 않는다).
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(cleaned[start : end + 1])


def make_openai_llm_call(model: str, api_key: str | None = None, client: Any | None = None) -> LLMCall:
    """OpenAI Chat Completions로 LLMCall을 구현한다.

    model은 필수 인자다 — 기본값을 두지 않아, 아직 확정되지 않은 모델을 실수로
    쓰는 걸 막는다. api_key를 None으로 두면 OpenAI SDK가 OPENAI_API_KEY
    환경변수를 사용한다. client는 테스트에서 실제 API 없이 검증할 때만 주입한다.
    """
    if client is None:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)

    def call(prompt: str) -> str:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        return response.choices[0].message.content

    return call
