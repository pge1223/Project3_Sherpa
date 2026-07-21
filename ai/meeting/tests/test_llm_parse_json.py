# 작성자: 용준/Claude(2026-07-20)
# 목적: ai/meeting/graph/llm.py::parse_json_response의 방어적 파싱(코드블록 제거, JSON 앞뒤
#       설명문 제거)을 검증한다. 이 함수는 배치형/대화형 ideation, reviewer/chair 노드가
#       모두 공유하므로, 정상 JSON·코드블록 JSON에 대한 동작이 바뀌지 않는지도 함께 확인한다.

import json
import sys
from pathlib import Path

import pytest

MEETING_DIR = Path(__file__).resolve().parents[1]  # ai/meeting
sys.path.insert(0, str(MEETING_DIR))

from graph.llm import parse_json_response  # noqa: E402


def test_parses_plain_json():
    assert parse_json_response('{"a": 1}') == {"a": 1}


def test_parses_json_wrapped_in_markdown_code_fence():
    text = '```json\n{"a": 1, "b": [1, 2]}\n```'
    assert parse_json_response(text) == {"a": 1, "b": [1, 2]}


def test_parses_json_with_leading_and_trailing_prose():
    text = '물론이죠! 요청하신 결과는 다음과 같습니다:\n{"a": 1}\n도움이 되었길 바랍니다.'
    assert parse_json_response(text) == {"a": 1}


def test_empty_response_raises():
    with pytest.raises(json.JSONDecodeError):
        parse_json_response("")


def test_response_without_any_json_object_raises():
    with pytest.raises(json.JSONDecodeError):
        parse_json_response("죄송합니다, 답변을 생성할 수 없습니다.")


def test_malformed_json_inside_prose_still_raises():
    text = "결과: {a: 1, 이것은 유효한 JSON이 아닙니다}"
    with pytest.raises(json.JSONDecodeError):
        parse_json_response(text)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
