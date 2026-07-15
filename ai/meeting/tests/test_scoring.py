# 작성자: 경이
# 목적: 점수 엔진(ai/meeting/scoring) 검증 — mock 재현, 결정론(동일입력=동일출력, TST-002 기반),
#       필수항목 누락 감점(MTG-003) 동작 확인.
# import: 표준 라이브러리 copy/json/sys/pathlib, pytest; ai/meeting/scoring 패키지.

import copy
import json
import sys
from pathlib import Path

MEETING_DIR = Path(__file__).resolve().parents[1]  # ai/meeting
sys.path.insert(0, str(MEETING_DIR))

from scoring import calculate_score  # noqa: E402

FIXTURE = MEETING_DIR / "tests" / "fixtures" / "final_meeting_result.v2.json"


def _load_data() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["data"]


def test_reproduces_mock_score_result():
    """rubric + reviewer_results 로 계산한 score_result 가 mock 의 값과 정확히 일치한다."""
    data = _load_data()
    result = calculate_score(data["rubric"], data["reviewer_results"])
    assert result == data["score_result"]


def test_deterministic_same_input_same_output():
    """동일 입력을 두 번 계산하면 완전히 동일한 결과가 나온다(MTG-003 검수 기준)."""
    data = _load_data()
    r1 = calculate_score(data["rubric"], data["reviewer_results"])
    r2 = calculate_score(data["rubric"], data["reviewer_results"])
    assert r1 == r2
    assert r1["total_score"] == 61


def test_missing_required_criterion_penalty():
    """필수 항목(marketability)을 아무도 채점하지 않으면 raw 0 + 누락 감점 표식이 생긴다."""
    data = _load_data()
    reviewers = copy.deepcopy(data["reviewer_results"])
    for r in reviewers:
        r["rubric_scores"] = [s for s in r["rubric_scores"] if s["criterion_id"] != "marketability"]

    result = calculate_score(data["rubric"], reviewers)

    mk = next(b for b in result["breakdown"] if b["criterion_id"] == "marketability")
    assert mk["raw_score"] == 0
    assert mk["source_review_ids"] == []
    assert any(
        p["type"] == "missing_required" and p["criterion_id"] == "marketability"
        for p in result["penalties"]
    )
    # 61 - marketability(20) = 41
    assert result["total_score"] == 41


def test_non_required_missing_has_no_penalty():
    """비필수 항목(differentiation) 누락은 감점 표식을 만들지 않는다."""
    data = _load_data()
    reviewers = copy.deepcopy(data["reviewer_results"])
    for r in reviewers:
        r["rubric_scores"] = [s for s in r["rubric_scores"] if s["criterion_id"] != "differentiation"]

    result = calculate_score(data["rubric"], reviewers)

    assert result["penalties"] == []
    # 61 - differentiation(11) = 50
    assert result["total_score"] == 50


def test_multiple_reviewers_same_criterion_average():
    """같은 기준을 두 위원이 채점하면 평균으로 집계하고 source_review_ids 를 모두 기록한다."""
    rubric = {
        "rubric_id": "R1",
        "total_max_score": 100,
        "criteria": [{"criterion_id": "c1", "criterion_name": "기준1", "max_score": 100, "required": True}],
    }
    reviewers = [
        {"review_id": "A", "rubric_scores": [{"criterion_id": "c1", "score": 80}]},
        {"review_id": "B", "rubric_scores": [{"criterion_id": "c1", "score": 70}]},
    ]
    result = calculate_score(rubric, reviewers)
    assert result["total_score"] == 75
    assert result["breakdown"][0]["source_review_ids"] == ["A", "B"]
