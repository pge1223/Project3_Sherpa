# 작성자: 경이
# 목적: LangGraph 회의 그래프(M4) 검증 — rubric 변환, raw->v2 위원/위원장 변환,
#       전체 그래프 실행(위원 병렬 → 점수 → 위원장 종합)이 review_output.schema.json
#       v2 계약을 만족하는 결과를 만드는지 확인한다. 실제 LLM 대신 고정 응답을 돌려주는
#       stub을 쓴다.
# import: 표준 라이브러리 json/pathlib, pytest, jsonschema; ai/meeting/graph 패키지.

import json
import sys
from pathlib import Path

import jsonschema

MEETING_DIR = Path(__file__).resolve().parents[1]  # ai/meeting
REPO_ROOT = MEETING_DIR.parents[1]
sys.path.insert(0, str(MEETING_DIR))

from graph import assemble_meeting_graph, build_routing, build_rubric, initial_state  # noqa: E402
from graph.transform import raw_chair_to_v2, raw_reviewer_to_v2  # noqa: E402
from graph.evidence import EvidencePool  # noqa: E402

SCHEMA_PATH = REPO_ROOT / "contracts" / "schemas" / "review_output.schema.json"
COMPETITION_MAPPING_PATH = MEETING_DIR / "personas" / "rubric_mapping_competition.json"


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _validate_against_defs(instance: dict, def_name: str) -> None:
    schema = _load_schema()
    sub_schema = {**schema["$defs"][def_name], "$defs": schema["$defs"]}
    jsonschema.Draft202012Validator(sub_schema).validate(instance)


# ---------------------------------------------------------------------------
# rubric.py
# ---------------------------------------------------------------------------


def test_build_rubric_from_competition_mapping_matches_v2_rubric_schema():
    mapping = json.loads(COMPETITION_MAPPING_PATH.read_text(encoding="utf-8"))
    rubric = build_rubric(mapping)
    _validate_against_defs(rubric, "rubric")
    assert rubric["total_max_score"] == 100
    assert all(c["required"] is True for c in rubric["criteria"])


def test_build_routing_maps_every_criterion_to_primary_persona():
    mapping = json.loads(COMPETITION_MAPPING_PATH.read_text(encoding="utf-8"))
    routing = build_routing(mapping)
    assert routing["creativity_appropriateness"]["primary"] == "creativity_originality"
    assert routing["feasibility"]["primary"] == "technical_feasibility"
    assert set(routing) == {c["criterion_id"] for c in mapping["rubric"]}


# ---------------------------------------------------------------------------
# transform.py (raw -> v2)
# ---------------------------------------------------------------------------

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
        },
        {
            "criterion_id": "differentiation",
            "criterion_name": "차별성",
            "max_score": 20,
            "score_recommendation": None,
            "judgment": "not_applicable",
            "confidence": "medium",
            "strengths": [],
            "weaknesses": [],
            "evidence_refs": [],
            "improvement_actions": [],
        },
    ],
    "cross_reviews": [],
    "priority_actions": [
        {"priority": 1, "criterion_id": "marketability", "action": "고객 인터뷰 보강", "reason": "근거 부족"}
    ],
    "out_of_scope": [
        {"topic": "AI 모델 구현", "reason": "기술 검토 필요", "handoff_persona_id": "technical_feasibility"}
    ],
}


def test_raw_reviewer_to_v2_excludes_not_applicable_and_matches_schema():
    pool = EvidencePool("business_strategy")
    result = raw_reviewer_to_v2(_RAW_REVIEWER, pool)
    _validate_against_defs(result, "reviewerResult")

    scored_ids = {s["criterion_id"] for s in result["rubric_scores"]}
    assert scored_ids == {"marketability"}, "not_applicable 항목은 채점 결과에서 빠져야 한다"
    assert result["rubric_scores"][0]["judgment"] == "needs_improvement"
    assert result["rubric_scores"][0]["evidence_ids"] == ["EV-business_strategy-001"]
    assert result["out_of_scope"][0]["topic"] == "AI 모델 구현"


_RAW_CHAIR = {
    "chair_id": "review_chair",
    "overall_assessment": "타깃 고객은 명확하나 시장 검증이 부족하다.",
    "consensus": ["문제 정의는 명확하다."],
    "disagreements": [],
    "top_strengths": ["타깃 고객이 구체적이다."],
    "top_risks": ["시장 검증 근거 부족"],
    "final_priority_actions": [
        {
            "priority": 1,
            "title": "고객 검증 자료 보강",
            "target": "시장성 섹션",
            "reason": "고객 인터뷰 결과가 없다.",
            "action": "고객 인터뷰 10건 이상을 추가한다.",
            "related_criteria": ["marketability"],
            "evidence_ids": ["EV-business_strategy-001"],
        }
    ],
    "final_decision": None,
    "decision_note": "합격 기준이 입력되지 않아 판정하지 않는다.",
}


def test_raw_chair_to_v2_matches_schema():
    chair_summary, top_revisions = raw_chair_to_v2(_RAW_CHAIR)
    _validate_against_defs(chair_summary, "chairSummary")
    for revision in top_revisions:
        _validate_against_defs(revision, "revision")
    assert top_revisions[0]["title"] == "고객 검증 자료 보강"


# ---------------------------------------------------------------------------
# 그래프 전체 실행 (stub LLM)
# ---------------------------------------------------------------------------

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
        },
        {
            "criterion_id": "execution_plan",
            "criterion_name": "실행계획",
            "max_score": 20,
            "score_recommendation": 12,
            "judgment": "critical_risk",
            "confidence": "high",
            "strengths": ["개발 기간이 명시되어 있다."],
            "weaknesses": ["병렬 작업이 과도하다."],
            "evidence_refs": [],
            "improvement_actions": ["MVP 범위를 축소한다."],
        },
    ],
    "cross_reviews": [
        {
            "target_persona_id": "business_strategy",
            "relation": "supplement",
            "target_criterion_id": "marketability",
            "comment": "시장 검증과 함께 기술 검증 계획도 필요하다.",
            "evidence_refs": [],
        }
    ],
    "priority_actions": [],
    "out_of_scope": [],
}

_RUBRIC = {
    "rubric_id": "RUBRIC-TEST",
    "total_max_score": 100,
    "criteria": [
        {"criterion_id": "marketability", "criterion_name": "시장성", "max_score": 30, "required": True},
        {
            "criterion_id": "technical_feasibility",
            "criterion_name": "기술·실현 가능성",
            "max_score": 30,
            "required": True,
        },
        {"criterion_id": "differentiation", "criterion_name": "차별성", "max_score": 20, "required": False},
        {"criterion_id": "execution_plan", "criterion_name": "실행계획", "max_score": 20, "required": True},
    ],
}

_RETRIEVED_EVIDENCE = [
    {
        "chunk_id": "chunk_001",
        "document_name": "사업계획서.pdf",
        "page": 3,
        "section": "문제 정의",
        "text": "초기 창업자는 지원사업 정보를 찾는 데 평균적으로 많은 시간을 사용한다.",
        "score": 0.87,
    }
]


def _make_stub_llm(raw_by_marker: dict[str, dict]):
    def stub_llm(prompt: str) -> str:
        for marker, raw in raw_by_marker.items():
            if marker in prompt:
                return json.dumps(raw, ensure_ascii=False)
        raise AssertionError(f"stub_llm: 프롬프트에서 마커를 찾지 못함(markers={list(raw_by_marker)})")

    return stub_llm


def test_full_meeting_graph_produces_v2_compliant_result():
    committee = ["business_strategy", "technical_feasibility"]
    llm_call = _make_stub_llm(
        {
            "사업전략 전문가입니다": _RAW_REVIEWER,
            "기술·실현가능성 전문가입니다": _TECHNICAL_RAW,
            "위원장(review_chair)입니다": _RAW_CHAIR,
        }
    )
    graph = assemble_meeting_graph(committee, llm_call)

    state = initial_state(
        meeting_id="MTG-TEST-001",
        domain="startup",
        rubric=_RUBRIC,
        submission={"document_name": "테스트 사업계획서.pdf", "text": "..."},
        committee=committee,
        retrieved_evidence=_RETRIEVED_EVIDENCE,
    )
    result = graph.invoke(state)

    # MTG-001: 두 위원 결과가 모두, 서로 덮어쓰지 않고 남아 있어야 한다
    assert set(result["reviewer_results"]) == {"business_strategy", "technical_feasibility"}
    # MTG-006: 마지막 노드(chair)까지 지나 완료 단계여야 한다
    assert result["stage"] == "완료"
    # MTG-003: 점수 엔진(M2) 결과가 결정론적으로 채워졌는지
    assert result["score_result"]["total_score"] == 20 + 18 + 12  # differentiation은 not_applicable로 미채점
    # MTG-002/004
    assert result["chair_summary"]["chair_id"] == "review_chair"
    assert 1 <= len(result["top_revisions"]) <= 5

    document = {
        "schema_version": "2.0.0",
        "meeting_id": result["meeting_id"],
        "project_id": "PRJ-TEST-001",
        "document_id": "DOC-TEST-001",
        "title": "테스트 회의",
        "status": "completed",
        "domain": result["domain"],
        "rubric": result["rubric"],
        "reviewer_results": list(result["reviewer_results"].values()),
        "score_result": result["score_result"],
        "chair_summary": result["chair_summary"],
        "top_revisions": result["top_revisions"],
        "evidence": result["evidence"],
        "media_script": [],
    }
    jsonschema.Draft202012Validator(_load_schema()).validate(document)
