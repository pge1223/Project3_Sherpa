# 작성자: 경이
# 목적: 특정 위원 재실행(MTG-007) 검증 — 지정 위원만 갱신되고 나머지 위원의 기존
#       결과는 그대로 유지되며, 점수·위원장 종합이 재종합되는지 확인한다.
# import: 표준 라이브러리 json/sys/pathlib, pytest, jsonschema; ai/meeting/graph 패키지.

import json
import sys
from pathlib import Path

import jsonschema

MEETING_DIR = Path(__file__).resolve().parents[1]  # ai/meeting
REPO_ROOT = MEETING_DIR.parents[1]
sys.path.insert(0, str(MEETING_DIR))

from graph import rerun_reviewer, run_meeting  # noqa: E402

SCHEMA_PATH = REPO_ROOT / "contracts" / "schemas" / "review_output.schema.json"
COMPETITION_MAPPING_PATH = MEETING_DIR / "personas" / "rubric_mapping_competition.json"

_PERSONA_NAMES = {
    "creativity_originality": "창의성·독창성 전문가",
    "technical_feasibility": "기술·실현가능성 전문가",
    "business_strategy": "사업전략 전문가",
    "presentation_completeness": "완성도·전달력 전문가",
}

_RAW_CHAIR = {
    "chair_id": "review_chair",
    "overall_assessment": "전반적으로 양호하다.",
    "consensus": ["아이디어가 참신하다."],
    "disagreements": [],
    "top_strengths": ["아이디어가 참신하다."],
    "top_risks": ["실현 가능성 검증이 더 필요하다."],
    "final_priority_actions": [
        {
            "priority": 1,
            "title": "실현 가능성 보강",
            "target": "실현 가능성 섹션",
            "reason": "구체적 실행 계획이 부족하다.",
            "action": "단계별 실행 계획을 추가한다.",
            "related_criteria": ["feasibility"],
            "evidence_ids": [],
        }
    ],
    "final_decision": None,
    "decision_note": None,
}


def _raw_reviewer(persona_id: str, criterion_id: str, criterion_name: str, score: int) -> dict:
    return {
        "review_id": f"REV-{persona_id}",
        "meeting_id": "MTG-RERUN-001",
        "persona_id": persona_id,
        "persona_name": _PERSONA_NAMES[persona_id],
        "review_round": 1,
        "review_summary": f"{_PERSONA_NAMES[persona_id]} 검토",
        "review_items": [
            {
                "criterion_id": criterion_id,
                "criterion_name": criterion_name,
                "max_score": 25,
                "score_recommendation": score,
                "judgment": "adequate",
                "confidence": "high",
                "strengths": ["근거가 있다."],
                "weaknesses": [],
                "evidence_refs": [],
                "improvement_actions": [],
            }
        ],
        "cross_reviews": [],
        "priority_actions": [],
        "out_of_scope": [],
    }


def _owned(mapping: dict) -> dict[str, tuple[str, str]]:
    """persona_id -> (criterion_id, criterion_name) (공모전 매핑은 1인 1항목)."""
    return {
        item["primary_persona_id"]: (item["criterion_id"], item["criterion_name"])
        for item in mapping["rubric"]
    }


def _stub(raw_by_marker: dict):
    def stub(prompt: str) -> str:
        for marker, raw in raw_by_marker.items():
            if marker in prompt:
                return json.dumps(raw, ensure_ascii=False)
        raise AssertionError(f"stub: 마커 못 찾음 (markers={list(raw_by_marker)})")

    return stub


def test_rerun_reviewer_updates_only_target_and_keeps_others():
    mapping = json.loads(COMPETITION_MAPPING_PATH.read_text(encoding="utf-8"))
    owned = _owned(mapping)

    # 1차: 전원 20점
    initial_markers = {
        f"{_PERSONA_NAMES[pid]}입니다": _raw_reviewer(pid, cid, cname, 20)
        for pid, (cid, cname) in owned.items()
    }
    initial_markers["위원장(review_chair)입니다"] = _RAW_CHAIR

    document = run_meeting(
        meeting_id="MTG-RERUN-001",
        project_id="PRJ-RERUN-001",
        document_id="DOC-RERUN-001",
        title="재실행 테스트",
        rubric_mapping=mapping,
        submission={"document_name": "test.pdf", "text": "..."},
        retrieved_evidence=[],
        llm_call=_stub(initial_markers),
    )
    assert document["score_result"]["total_score"] == 80  # 20 * 4

    original_by_persona = {r["persona_id"]: r for r in document["reviewer_results"]}

    # 2차: creativity_originality 위원만 10점으로 재평가
    target = "creativity_originality"
    tcid, tcname = owned[target]
    rerun_markers = {
        f"{_PERSONA_NAMES[target]}입니다": _raw_reviewer(target, tcid, tcname, 10),
        "위원장(review_chair)입니다": _RAW_CHAIR,
    }

    updated = rerun_reviewer(
        previous_document=document,
        persona_id=target,
        rubric_mapping=mapping,
        submission={"document_name": "test.pdf", "text": "..."},
        retrieved_evidence=[],
        llm_call=_stub(rerun_markers),
    )

    jsonschema.Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))).validate(updated)

    updated_by_persona = {r["persona_id"]: r for r in updated["reviewer_results"]}

    # 위원 수는 그대로
    assert set(updated_by_persona) == set(original_by_persona)
    # 재실행 위원: 점수 갱신됨
    target_score = updated_by_persona[target]["rubric_scores"][0]["score"]
    assert target_score == 10
    # 나머지 위원: 기존 결과 그대로 유지(MTG-007 검수 기준)
    for pid in original_by_persona:
        if pid != target:
            assert updated_by_persona[pid] == original_by_persona[pid]
    # 점수 재종합: 80 - (20 - 10) = 70
    assert updated["score_result"]["total_score"] == 70


def test_rerun_reviewer_rejects_persona_not_in_committee():
    import pytest

    mapping = json.loads(COMPETITION_MAPPING_PATH.read_text(encoding="utf-8"))
    fake_document = {
        "meeting_id": "MTG-X",
        "project_id": "PRJ-X",
        "document_id": "DOC-X",
        "rubric": {"rubric_id": "R", "total_max_score": 100, "criteria": []},
        "reviewer_results": [],
        "evidence": [],
    }
    with pytest.raises(ValueError):
        rerun_reviewer(
            previous_document=fake_document,
            persona_id="policy_fit",  # 공모전 위원회에 없음
            rubric_mapping=mapping,
            submission={},
            retrieved_evidence=[],
            llm_call=lambda p: "{}",
        )
