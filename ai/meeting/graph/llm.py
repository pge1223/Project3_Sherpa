# 작성자: 경이
# 목적: LangGraph 노드가 사용하는 LLM 호출 인터페이스와 JSON 파싱 유틸(M4). 실제 API
#       연동(OpenAI/Anthropic)은 이 시그니처(str -> str)를 구현하는 함수를 넣기만 하면
#       되도록 인터페이스만 분리해 둔다. 테스트에서는 고정 응답을 돌려주는 stub 함수를 쓴다.
# import: 표준 라이브러리 json, typing.

from __future__ import annotations

import json
from typing import Callable

LLMCall = Callable[[str], str]


def parse_json_response(text: str) -> dict:
    """LLM 응답 문자열에서 JSON 객체를 파싱한다.

    프롬프트는 마크다운 코드블록 없이 JSON만 반환하라고 지시하지만, 실제 LLM은 종종
    ```json ... ``` 로 감싸 응답하므로 방어적으로 벗겨낸다.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    return json.loads(cleaned)
