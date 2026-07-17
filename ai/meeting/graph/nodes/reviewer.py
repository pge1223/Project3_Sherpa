# 작성자: 경이
# 목적: LangGraph reviewer 노드(M4, MTG-001 / RAG-003·004·005 연동). 위원 1명을 독립적으로
#       실행해 rubric·검색 근거로 검토하고, raw 출력을 v2 reviewerResult로 변환해 State에
#       반영한다. State에 evidence_context(용준 RAG 어댑터)가 있으면 ①(persona,criterion)별
#       사전 prompt_guard를 프롬프트에 넣고, ②의견 생성 후 criterion마다 evidence_callback을
#       불러 RAG-004 근거 연결 + RAG-005 최종 판정을 받아, ③A안(근거는 RAG-004로 교체) +
#       최종 sufficiency 게이팅을 적용한다. evidence_context가 없으면 기존 flat
#       retrieved_evidence 경로로 그대로 동작한다(하위호환). 콜백은 backend가 주입하는
#       Callable이라 이 노드는 ai/rag를 직접 import하지 않는다(회의 ↔ RAG 분리 유지).
# import: prompts.build_reviewer_prompt(형제 패키지), 같은 패키지의 evidence/llm/state/transform.

from __future__ import annotations

from typing import Callable

from prompts import build_reviewer_prompt

from ..evidence import EvidencePool
from ..llm import LLMCall, parse_json_response
from ..state import MeetingState
from ..transform import raw_reviewer_to_v2

# backend가 주입하는 근거 콜백:
# (persona_id, criterion_id, review_item) -> {"linked_evidence_refs": [...],
#                                             "sufficiency": {"allow_numeric_score": bool, ...}}
EvidenceCallback = Callable[[str, str, dict], dict]


def _dedupe_by_chunk(items: list[dict]) -> list[dict]:
    """chunk_id 기준 중복 제거(먼저 등장한 것 유지). 여러 criterion의 retrieved_evidence를
    한 위원 프롬프트에 합칠 때 같은 청크가 중복 노출되지 않게 한다."""
    seen: set = set()
    out: list[dict] = []
    for it in items:
        cid = it.get("chunk_id")
        if cid in seen:
            continue
        if cid is not None:
            seen.add(cid)
        out.append(it)
    return out


def make_reviewer_node(
    persona_id: str,
    llm_call: LLMCall,
    evidence_callback: EvidenceCallback | None = None,
) -> Callable[[MeetingState], dict]:
    """persona_id 위원 전용 노드 함수를 만든다. 1회차 독립 평가(MTG-001)만 다룬다."""

    def reviewer_node(state: MeetingState) -> dict:
        my_ctx = [
            e for e in (state.get("evidence_context") or []) if e.get("persona_id") == persona_id
        ]

        if my_ctx:
            # RAG 연동 경로: (persona,criterion)별 근거를 합치고 사전 guard를 모은다.
            retrieved = _dedupe_by_chunk(
                [ev for e in my_ctx for ev in (e.get("retrieved_evidence") or [])]
            )
            guards = [
                (e["criterion_id"], (e.get("sufficiency") or {}).get("prompt_guard", ""))
                for e in my_ctx
            ]
        else:
            # 레거시 경로: flat retrieved_evidence만 사용.
            retrieved = state["retrieved_evidence"]
            guards = None

        prompt = build_reviewer_prompt(
            persona_id,
            state["rubric"],
            state["submission"],
            retrieved,
            evidence_guards=guards,
        )
        raw = parse_json_response(llm_call(prompt))

        pool = EvidencePool(persona_id, retrieved)

        criterion_evidence: dict[str, dict] | None = None
        if evidence_callback is not None and my_ctx:
            # 의견 생성 후, criterion마다 RAG-004 링크 + RAG-005 최종 판정을 받는다.
            criterion_evidence = {}
            for item in raw.get("review_items", []):
                cid = item.get("criterion_id")
                if cid is None:
                    continue
                criterion_evidence[cid] = evidence_callback(persona_id, cid, item)

        v2_result = raw_reviewer_to_v2(raw, pool, criterion_evidence=criterion_evidence)
        return {
            "reviewer_results": {persona_id: v2_result},
            "evidence": pool.as_list(),
        }

    return reviewer_node
