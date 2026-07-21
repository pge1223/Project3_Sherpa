# 작성자: 경이
# 목적: 개발 위원 피드백 개인화(구현 난이도 판정 + 가이드) 검증 — 프로필별 결정론 판정,
#       상세도 매핑, 해결된 지적 제외, 프로필 없음 폴백, llm_call 주입 시 산문 생성.
# import: 표준 라이브러리 sys/pathlib/json; ai/meeting/scoring 패키지.

import json
import sys
from pathlib import Path

MEETING_DIR = Path(__file__).resolve().parents[1]  # ai/meeting
sys.path.insert(0, str(MEETING_DIR))

from scoring import (  # noqa: E402
    attach_impl_guides,
    build_impl_guide,
    classify_impl_difficulty,
    is_technical_persona,
)

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "user_profile_samples.json"
_PROFILES = {p["profile_id"]: p for p in json.loads(_FIXTURE.read_text(encoding="utf-8"))["profiles"]}
_NONMAJOR = _PROFILES["sample-nonmajor"]
_MAJOR = _PROFILES["sample-major"]


def test_nonmajor_is_hard_and_detailed():
    c = classify_impl_difficulty(_NONMAJOR)
    assert c["level"] == "hard"
    assert c["verbosity"] == "detailed"
    assert c["score"] < 2


def test_major_is_easy_and_brief():
    c = classify_impl_difficulty(_MAJOR)
    assert c["level"] == "easy"
    assert c["verbosity"] == "brief"
    assert c["score"] >= 5
    # 근거가 사람이 읽을 수 있게 남는다
    assert "기술 계열 전공" in c["signals"]


def test_middle_profile_is_moderate():
    # 전공은 아니지만 인턴+공모전 경험이 있는 중간 프로필 → moderate
    mid = {
        "education": {"is_technical_major": False, "degree": "bachelor"},
        "experience": {"it_internship_months": 6, "competition_participations": 1},
        "github": {"has_backend_experience": False, "relevant_projects": 0, "total_commits": 50},
    }
    c = classify_impl_difficulty(mid)
    assert c["level"] == "moderate"
    assert c["verbosity"] == "standard"


def test_no_profile_returns_none():
    assert classify_impl_difficulty(None) is None
    assert classify_impl_difficulty({}) is None
    assert build_impl_guide({"id": "f-stack", "text": "x"}, None) is None


def test_missing_github_and_experience_defaults_to_hard():
    # 마이페이지에서 GitHub·이력을 안 낸 비전공자도 안전하게 동작(신호 없음 → hard)
    minimal = {"education": {"is_technical_major": False, "degree": "bachelor"}}
    c = classify_impl_difficulty(minimal)
    assert c["level"] == "hard"


def test_resolved_feedback_gets_no_guide():
    resolved = {"id": "f-stack", "status": "resolved", "text": "모델 미명시", "note": "반영함"}
    assert build_impl_guide(resolved, _NONMAJOR) is None


def test_guide_without_llm_has_classification_but_no_prose():
    fb = {"id": "f-stack", "status": "open", "text": "모델 미명시", "suggestion": "KURE-v1 명시"}
    g = build_impl_guide(fb, _MAJOR)
    assert g["level"] == "easy"
    assert g["verbosity"] == "brief"
    assert g["feedback_id"] == "f-stack"
    assert g["prose"] is None


def test_guide_with_llm_fills_prose_and_uses_verbosity():
    captured = {}

    def fake_llm(prompt: str) -> str:
        captured["prompt"] = prompt
        return json.dumps({"guide": "① KURE-v1을 그대로 쓰세요 ..."})

    fb = {"id": "f-stack", "status": "open", "text": "모델 미명시", "suggestion": "KURE-v1 명시"}
    g = build_impl_guide(fb, _NONMAJOR, llm_call=fake_llm)
    assert g["prose"].startswith("①")
    # 비전공자(detailed) 지시가 프롬프트에 반영됐는지
    assert "단계별" in captured["prompt"]


def test_guide_with_malformed_llm_output_falls_back_to_none_prose():
    fb = {"id": "f-eval", "status": "open", "text": "검증 없음"}
    g = build_impl_guide(fb, _MAJOR, llm_call=lambda _p: "not json")
    assert g["prose"] is None
    assert g["level"] == "easy"


def test_is_technical_persona_whitelist():
    # 도메인 위원회의 기술 위원만 True — 기획/사업/완성도 위원은 False
    assert is_technical_persona("technical_feasibility") is True
    assert is_technical_persona("dev_expert") is True
    assert is_technical_persona("business_strategy") is False
    assert is_technical_persona("creativity_originality") is False
    assert is_technical_persona("presentation_completeness") is False
    assert is_technical_persona(None) is False


def test_attach_skips_resolved_and_maps_rest():
    dev_feedback = [
        {"id": "f-stack", "status": "resolved", "text": "x", "note": "y"},
        {"id": "f-eval", "status": "open", "text": "검증 없음"},
        {"id": "f-scale", "status": "new", "text": "부하 추정 없음"},
    ]
    guides = attach_impl_guides(dev_feedback, _NONMAJOR)
    assert [g["feedback_id"] for g in guides] == ["f-eval", "f-scale"]
    assert all(g["level"] == "hard" for g in guides)
