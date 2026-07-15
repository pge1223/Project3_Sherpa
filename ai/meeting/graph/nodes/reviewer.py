# 작성자: 경이
# 목적: LangGraph reviewer 노드(M4, MTG-001). 위원 1명을 독립적으로 실행해 rubric과
#       검색 근거를 바탕으로 검토하고, raw 출력을 v2 reviewerResult로 변환해 State에
#       반영한다. persona_id별로 노드 함수를 따로 만들어(make_reviewer_node) 자신의
#       결과만 반환하게 하고, 병합은 state.py의 리듀서가 처리한다 — 노드 자체는 다른
#       위원의 reviewer_results를 읽지 않는다.
# import: prompts.build_reviewer_prompt(형제 패키지 — 호출 시점에 ai/meeting이
#         sys.path에 있어야 한다, 기존 test_scoring.py와 동일한 관례), 같은 패키지의
#         evidence/llm/state/transform.

from __future__ import annotations

from typing import Callable

from prompts import build_reviewer_prompt

from ..evidence import EvidencePool
from ..llm import LLMCall, parse_json_response
from ..state import MeetingState
from ..transform import raw_reviewer_to_v2


def make_reviewer_node(persona_id: str, llm_call: LLMCall) -> Callable[[MeetingState], dict]:
    """persona_id 위원 전용 노드 함수를 만든다.

    1회차 독립 평가(MTG-001)만 다룬다 — previous_reviews는 항상 비워 보낸다.
    """

    def reviewer_node(state: MeetingState) -> dict:
        prompt = build_reviewer_prompt(
            persona_id,
            state["rubric"],
            state["submission"],
            state["retrieved_evidence"],
        )
        raw = parse_json_response(llm_call(prompt))
        pool = EvidencePool(persona_id, state["retrieved_evidence"])
        v2_result = raw_reviewer_to_v2(raw, pool)
        return {
            "reviewer_results": {persona_id: v2_result},
            "evidence": pool.as_list(),
        }

    return reviewer_node
