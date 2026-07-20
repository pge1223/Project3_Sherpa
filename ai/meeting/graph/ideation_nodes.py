# 작성자: 용준/Claude(2026-07-20)
# 목적: "아이디어 발전 회의(ideation)" LangGraph 노드. 기획 전문가(planning_expert)/개발
#       전문가(dev_expert)가 순차로 실행되며 서로의 직전 발언을 참조하고, 회의 진행자
#       (ideation_facilitator)가 라운드 종료 시 합의/이견/다음 행동을 판단하고, 최종
#       종합 노드가 아이디어 제안서를 만든다.
# import: prompts.build_ideation_turn_prompt 등(형제 패키지), 같은 패키지의 llm/state.

from __future__ import annotations

from typing import Any, Callable

from prompts import (
    build_ideation_facilitator_prompt,
    build_ideation_synthesis_prompt,
    build_ideation_turn_prompt,
)

from .ideation_state import IdeationState
from .llm import LLMCall, parse_json_response

# backend가 주입하는 근거 조회 콜백: (persona_id, topic_query) -> retrieved_evidence(list[dict]).
# criterion 개념이 없는 ideation 모드에서는 RAG-004(근거 연결) 사후 링크 대신, 사전 검색
# 결과를 그대로 프롬프트에 넣는다(ai/rag/orchestration/ideation_evidence_service.py 참고).
# None이면 근거 없이 진행한다(검색 결과가 비면 프롬프트 스스로 "근거 부족"으로 처리하도록
# ideation_common.txt 근거 사용 규칙에 이미 명시돼 있다).
EvidenceLookup = Callable[[str, str], list[dict]]

_VALID_STANCES = {"동의", "조건부_동의", "반박", "보완", "대안_제시", "사용자에게_질문"}
_TURN_LIST_FIELDS = (
    "observations",
    "proposals",
    "risks",
    "questions_for_expert",
    "questions_for_user",
    "evidence",
    "unresolved_issues",
)


def _topic_query(state: IdeationState) -> str:
    """근거 검색 질의를 만든다. 라운드 1은 사용자 아이디어 자체를, 이후 라운드는 아직
    풀리지 않은 쟁점을 우선한다(같은 검색을 반복하지 않기 위함)."""
    if state["round"] > 1 and state.get("unresolved_issues"):
        return " ".join(state["unresolved_issues"])
    idea = state["user_idea"]
    if isinstance(idea, dict):
        return " ".join(str(v) for v in idea.values() if v)
    return str(idea)


def _normalize_turn(raw: dict[str, Any], persona_id: str, round_number: int) -> dict[str, Any]:
    """LLM이 반환한 turn(raw)을 정규화한다.

    speaker_id/round는 LLM 출력을 신뢰하지 않고 항상 호출부가 아는 값으로 덮어쓴다 —
    기존 위원 평가 파이프라인(ai/meeting/graph/run.py::assemble_document())에서 LLM이
    persona_id를 지어내 committee 매칭이 깨졌던 것과 같은 사고를 방지하기 위한 동일한
    안전장치다. stance가 허용값이 아니면 "보완"으로 보수적으로 대체한다(회의가 어떤
    stance도 없이 진행되는 것을 막기 위함).
    """
    stance = raw.get("stance")
    if stance not in _VALID_STANCES:
        stance = "보완"
    turn = {
        "speaker_id": persona_id,
        "speaker_name": raw.get("speaker_name", persona_id),
        "role": raw.get("role", ""),
        "round": round_number,
        "topic": raw.get("topic", ""),
        "stance": stance,
        "summary": raw.get("summary", ""),
    }
    for field in _TURN_LIST_FIELDS:
        turn[field] = raw.get(field) or []
    return turn


def _round_context(state: IdeationState) -> dict[str, Any]:
    turns = state["turns"]
    return {
        "round": state["round"],
        "previous_turn": turns[-1] if turns else None,
        "consensus_so_far": state["consensus"],
        "unresolved_issues": state["unresolved_issues"],
        "user_answer": state.get("user_answer"),
    }


def _safe_call_json(llm_call: LLMCall, prompt: str) -> tuple[dict[str, Any] | None, bool]:
    """LLM 호출 + JSON 파싱을 시도하고, 실패하면 한 번 재시도한다.

    요청 9번 14항(모델 호출 실패·JSON 파싱 실패 시 폴백)에 따라, 두 번째 시도도 실패하면
    예외를 올리지 않고 (None, False)를 반환해 호출부가 stage="실패"로 그래프를 안전하게
    끝낼 수 있게 한다(기존 reviewer/chair 노드에는 이 폴백이 없었으나, 회의 도중 사용자
    응답을 기다리는 흐름이 새로 생긴 ideation 모드에서는 실패를 조용히 전파시키지 않는
    것이 더 안전하다는 판단).
    """
    for _ in range(2):
        try:
            return parse_json_response(llm_call(prompt)), True
        except (ValueError, KeyError, TypeError):
            continue
    return None, False


def make_ideation_expert_node(
    persona_id: str,
    llm_call: LLMCall,
    evidence_lookup: EvidenceLookup | None = None,
) -> Callable[[IdeationState], dict]:
    """persona_id(planning_expert 또는 dev_expert) 전문가 1턴 노드를 만든다.

    같은 그래프 안에서 순차로 실행되므로(요청 5번 핵심 요구사항), _round_context()가
    state["turns"][-1](상대 전문가의 직전 발언)을 그대로 프롬프트에 넣을 수 있다 —
    기존 심사형 그래프(reviewer 노드, 완전 병렬)에서는 불가능했던 부분이다.
    """

    def node(state: IdeationState) -> dict:
        query = _topic_query(state)
        retrieved = evidence_lookup(persona_id, query) if evidence_lookup is not None else []
        prompt = build_ideation_turn_prompt(
            persona_id,
            state["notice_and_criteria"],
            state["user_idea"],
            retrieved,
            _round_context(state),
        )
        raw, ok = _safe_call_json(llm_call, prompt)
        if not ok:
            return {"stage": "실패", "failed_node": f"expert__{persona_id}"}
        turn = _normalize_turn(raw, persona_id, state["round"])
        return {"turns": [turn]}

    return node


def make_facilitator_node(llm_call: LLMCall) -> Callable[[IdeationState], dict]:
    """라운드 종료 노드. 이번 라운드 두 전문가 발언을 종합해 합의/이견을 정리하고,
    다음 행동(continue_round/ask_user/finalize)을 판단한다.

    round_number >= max_rounds이면 LLM이 무엇을 반환하든 next_action을 "finalize"로
    강제한다(요청 9번 10항 "무한 반복 방지" — 서버가 신뢰하지 않고 직접 재계산하는 것은
    기존 rubric.py::build_dynamic_rubric_mapping()의 "배점 합계를 항상 서버에서
    재계산" 정책과 같은 원칙이다). continue_round면 round를 1 증가시킨다.
    """

    def node(state: IdeationState) -> dict:
        round_number = state["round"]
        turns_this_round = [t for t in state["turns"] if t.get("round") == round_number]
        prompt = build_ideation_facilitator_prompt(
            state["notice_and_criteria"],
            state["user_idea"],
            round_number,
            state["max_rounds"],
            turns_this_round,
            state["consensus"],
            state["unresolved_issues"],
        )
        raw, ok = _safe_call_json(llm_call, prompt)
        if not ok:
            return {"stage": "실패", "failed_node": "facilitator"}

        next_action = raw.get("next_action")
        if round_number >= state["max_rounds"]:
            next_action = "finalize"
        elif next_action not in ("continue_round", "ask_user", "finalize"):
            next_action = "continue_round"

        new_consensus = list(state["consensus"])
        for item in raw.get("consensus", []) or []:
            if item not in new_consensus:
                new_consensus.append(item)

        update: dict[str, Any] = {
            "consensus": new_consensus,
            "unresolved_issues": raw.get("unresolved_issues", []) or [],
            "next_action": next_action,
        }
        if next_action == "ask_user":
            # round도 증가시킨다 — resume_ideation_state()로 재개되면 그래프가 다시
            # START부터 planning_expert를 돈다. round를 그대로 두면 이미 발언이 쌓인
            # 같은 라운드 번호로 새 turn이 또 쌓여 라운드 경계가 헷갈린다. 사용자 답변을
            # 반영한 다음 발언들은 새 라운드로 취급하는 게 자연스럽다.
            update["stage"] = "사용자_대기"
            update["pending_question"] = raw.get("question_for_user")
            update["round"] = round_number + 1
        elif next_action == "finalize":
            update["stage"] = "종합"
            update["pending_question"] = None
        else:
            update["stage"] = "진행중"
            update["pending_question"] = None
            update["round"] = round_number + 1
        return update

    return node


def make_synthesis_node(llm_call: LLMCall) -> Callable[[IdeationState], dict]:
    """회의 종료 시(next_action="finalize") 전체 발언과 누적 합의/미해결 쟁점으로
    최종 아이디어 제안서를 조립한다."""

    def node(state: IdeationState) -> dict:
        prompt = build_ideation_synthesis_prompt(
            state["notice_and_criteria"],
            state["user_idea"],
            state["turns"],
            state["consensus"],
            state["unresolved_issues"],
        )
        raw, ok = _safe_call_json(llm_call, prompt)
        if not ok:
            return {"stage": "실패", "failed_node": "synthesis"}
        return {"idea_proposal": raw, "stage": "완료"}

    return node
