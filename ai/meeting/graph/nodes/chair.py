# 작성자: 경이
# 목적: LangGraph chair 노드(M4, MTG-002/004). 모든 위원의 v2 reviewer_results를 종합해
#       chair_summary와 top_revisions(최대 5개)를 만든다. "새 근거·점수를 임의로 만들지
#       않는다"는 원칙은 chair_prompt.txt의 [종합 원칙]이 프롬프트 레벨에서 강제하고,
#       여기서는 raw 출력을 v2 구조로 옮기기만 한다.
# import: prompts.build_chair_prompt(형제 패키지 — 호출 시점에 ai/meeting이 sys.path에
#         있어야 한다), 같은 패키지의 llm/state/transform.

from __future__ import annotations

from typing import Callable

from prompts import build_chair_prompt

from ..llm import LLMCall, parse_json_response
from ..state import MeetingState
from ..transform import raw_chair_to_v2


def make_chair_node(llm_call: LLMCall) -> Callable[[MeetingState], dict]:
    def chair_node(state: MeetingState) -> dict:
        prompt = build_chair_prompt(
            state["reviewer_results"],
            state["rubric"],
            state["evidence"],
        )
        raw = parse_json_response(llm_call(prompt))
        chair_summary, top_revisions = raw_chair_to_v2(raw)
        return {
            "chair_summary": chair_summary,
            "top_revisions": top_revisions,
            "stage": "완료",
        }

    return chair_node
