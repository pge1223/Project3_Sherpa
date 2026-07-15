# 작성자: 가은 (경이 합의, MTG-007)
# 목적: assemble_reevaluation_graph/reevaluation_state가 "선택 위원 외 기존 결과 유지"라는
#       MTG-007 검수 기준을 지키는지 확인한다. test_graph.py의 stub LLM 패턴을 그대로 쓴다.

import json
import sys
from pathlib import Path

MEETING_DIR = Path(__file__).resolve().parents[1]  # ai/meeting
sys.path.insert(0, str(MEETING_DIR))

from graph import (  # noqa: E402
    assemble_meeting_graph,
    assemble_reevaluation_graph,
    initial_state,
    reevaluation_state,
)

_RAW_REVIEWER = {
    "review_id": "REV-TEST-001",
    "meeting_id": "MTG-TEST-001",
    "persona_id": "business_strategy",
    "persona_name": "사업전략 전문가",
    "review_round": 1,
    "review_summary": "타깃 고객은 명확하나 시장 검증 근거가 부족하다.",
    "review_items": [
        {
            "criterion_id": "marketability",
            "criterion_name": "시장성",
            "max_score": 30,
            "score_recommendation": 20,
            "judgment": "needs_improvement",
            "confidence": "high",
            "strengths": ["타깃 고객이 구체적이다."],
            "weaknesses": ["고객 검증 자료가 없다."],
            "evidence_refs": [
                {
                    "source_id": "document_001",
                    "chunk_id": "chunk_001",
                    "source_type": "submission",
                    "page": 3,
                    "quote": "초기 창업자는 지원사업 정보를 찾는 데 많은 시간을 쓴다.",
                    "relevance": "문제 정의 근거",
                }
            ],
            "improvement_actions": ["고객 인터뷰 결과를 추가한다."],
        }
    ],
    "cross_reviews": [],
    "priority_actions": [],
    "out_of_scope": [],
}

_TECHNICAL_RAW = {
    "review_id": "REV-TEST-002",
    "meeting_id": "MTG-TEST-001",
    "persona_id": "technical_feasibility",
    "persona_name": "기술·실현가능성 전문가",
    "review_round": 1,
    "review_summary": "일정이 촉박해 위험이 크다.",
    "review_items": [
        {
            "criterion_id": "technical_feasibility",
            "criterion_name": "기술·실현 가능성",
            "max_score": 30,
            "score_recommendation": 18,
            "judgment": "needs_improvement",
            "confidence": "high",
            "strengths": ["핵심 입력 데이터가 명시되어 있다."],
            "weaknesses": ["데이터 확보 방법이 없다."],
            "evidence_refs": [],
            "improvement_actions": ["데이터 확보 계획을 추가한다."],
        }
    ],
    "cross_reviews": [],
    "priority_actions": [],
    "out_of_scope": [],
}

_RAW_CHAIR_V1 = {
    "chair_id": "review_chair",
    "overall_assessment": "1차 종합 의견.",
    "consensus": [],
    "disagreements": [],
    "top_strengths": [],
    "top_risks": [],
    "final_priority_actions": [
        {
            "priority": 1,
            "title": "고객 검증 자료 보강",
            "target": "시장성 섹션",
            "reason": "고객 인터뷰 결과가 없다.",
            "action": "고객 인터뷰 10건 이상을 추가한다.",
            "related_criteria": ["marketability"],
            "evidence_ids": [],
        }
    ],
    "final_decision": None,
    "decision_note": None,
}

_RUBRIC = {
    "rubric_id": "RUBRIC-TEST",
    "total_max_score": 60,
    "criteria": [
        {"criterion_id": "marketability", "criterion_name": "시장성", "max_score": 30, "required": True},
        {
            "criterion_id": "technical_feasibility",
            "criterion_name": "기술·실현 가능성",
            "max_score": 30,
            "required": True,
        },
    ],
}


def _make_stub_llm(raw_by_marker: dict[str, dict]):
    def stub_llm(prompt: str) -> str:
        for marker, raw in raw_by_marker.items():
            if marker in prompt:
                return json.dumps(raw, ensure_ascii=False)
        raise AssertionError(f"stub_llm: 프롬프트에서 마커를 찾지 못함(markers={list(raw_by_marker)})")

    return stub_llm


def _run_full_meeting():
    committee = ["business_strategy", "technical_feasibility"]
    llm_call = _make_stub_llm(
        {
            "사업전략 전문가입니다": _RAW_REVIEWER,
            "기술·실현가능성 전문가입니다": _TECHNICAL_RAW,
            "위원장(review_chair)입니다": _RAW_CHAIR_V1,
        }
    )
    graph = assemble_meeting_graph(committee, llm_call)
    state = initial_state(
        meeting_id="MTG-TEST-001",
        domain="startup",
        rubric=_RUBRIC,
        submission={"document_name": "테스트.pdf", "text": "..."},
        committee=committee,
        retrieved_evidence=[],
    )
    return graph.invoke(state)


def test_reevaluate_only_targeted_persona_changes():
    first_result = _run_full_meeting()
    assert first_result["reviewer_results"]["business_strategy"]["rubric_scores"][0]["score"] == 20

    # business_strategy만 재평가 — 새 점수(20 -> 27)로 바뀐 raw 응답을 stub으로 준다.
    updated_raw = json.loads(json.dumps(_RAW_REVIEWER))
    updated_raw["review_id"] = "REV-TEST-001-V2"
    updated_raw["review_summary"] = "재평가: 시장 검증 근거가 보강되어 점수를 상향한다."
    updated_raw["review_items"][0]["score_recommendation"] = 27
    updated_raw["review_items"][0]["judgment"] = "strong"

    updated_chair = json.loads(json.dumps(_RAW_CHAIR_V1))
    updated_chair["overall_assessment"] = "재평가 반영 후 종합 의견."

    reeval_llm = _make_stub_llm(
        {
            "사업전략 전문가입니다": updated_raw,
            "위원장(review_chair)입니다": updated_chair,
        }
    )

    reeval_graph = assemble_reevaluation_graph("business_strategy", reeval_llm)
    reeval_input = reevaluation_state(first_result, "business_strategy")
    second_result = reeval_graph.invoke(reeval_input)

    # 재평가 대상 위원은 새 결과로 바뀐다
    assert second_result["reviewer_results"]["business_strategy"]["review_id"] == "REV-TEST-001-V2"
    assert second_result["reviewer_results"]["business_strategy"]["rubric_scores"][0]["score"] == 27

    # MTG-007 검수 기준: 선택 위원 외 기존 결과는 그대로 유지
    assert (
        second_result["reviewer_results"]["technical_feasibility"]
        == first_result["reviewer_results"]["technical_feasibility"]
    )

    # 재평가 위원의 evidence는 새로 생성된 것으로 교체되고(중복 없이), 다른 위원 근거는 유지
    business_strategy_evidence = [
        e for e in second_result["evidence"] if e["evidence_id"].startswith("EV-business_strategy-")
    ]
    assert len(business_strategy_evidence) == 1  # 예전 근거와 중복으로 쌓이지 않음
    assert business_strategy_evidence[0]["quote"] == "초기 창업자는 지원사업 정보를 찾는 데 많은 시간을 쓴다."

    # score_result/chair_summary는 갱신된 reviewer_results를 반영해 재계산된다
    assert second_result["score_result"]["total_score"] == 27 + 18
    assert second_result["chair_summary"]["overall_assessment"] == "재평가 반영 후 종합 의견."
    assert second_result["stage"] == "완료"


def test_reevaluate_rejects_persona_outside_committee():
    first_result = _run_full_meeting()
    try:
        reevaluation_state(first_result, "presentation_completeness")
        assert False, "committee에 없는 persona_id는 ValueError가 나야 한다"
    except ValueError:
        pass
