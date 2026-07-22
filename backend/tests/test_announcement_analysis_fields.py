from app.api.routes.documents import (
    _ANNOUNCEMENT_ANALYSIS_CACHE_VERSION,
    _build_announcement_analysis_prompt,
    _build_official_facts,
    _missing_announcement_details,
)


def test_announcement_prompt_requests_all_detailed_fact_groups():
    prompt = _build_announcement_analysis_prompt("평가 기준과 주요 일정이 있는 공고문")

    for field in (
        "evaluation_criteria",
        "disqualification_rules",
        "application_review_conditions",
        "key_dates",
        "selection_benefits",
    ):
        assert field in prompt
    assert "평가 대상/부문" in prompt
    assert "모든 주요 일정" in prompt
    assert "서로 독립된 사실 하나" in prompt
    assert _ANNOUNCEMENT_ANALYSIS_CACHE_VERSION >= 2


def test_detailed_official_facts_are_not_dropped():
    facts = _build_official_facts(
        {
            "evaluation_criteria": [
                "기업 평가 · 혁신성: 20점",
                "도시 평가 · 계획 적정성: 20점",
            ],
            "disqualification_rules": ["증빙자료를 제출할 수 없는 경우 수상 취소"],
            "application_review_conditions": ["심사위원 판단으로 신청 분야가 변경될 수 있음"],
            "key_dates": ["평가: 8월 19일", "시상식: 9월 10일 17:30~19:00"],
            "selection_benefits": ["기업설명회 기회", "해외 바이어 대상 수상기업 안내"],
        }
    )

    assert facts.evaluation_criteria == [
        "기업 평가 · 혁신성: 20점",
        "도시 평가 · 계획 적정성: 20점",
    ]
    assert facts.disqualification_rules == ["증빙자료를 제출할 수 없는 경우 수상 취소"]
    assert facts.application_review_conditions == ["심사위원 판단으로 신청 분야가 변경될 수 있음"]
    assert facts.key_dates[-1] == "시상식: 9월 10일 17:30~19:00"
    assert facts.selection_benefits == ["기업설명회 기회", "해외 바이어 대상 수상기업 안내"]


def test_missing_schedule_and_pdf_details_trigger_audit():
    source = """
    [출처 문서: 공고문.pdf]
    혁신성 20점 사회적 가치성 20점
    진행절차 공모 신청 평가 결과 발표 시상식 6.29~7.24 8.19 8.24 9.10
    결과발표 8.24
    시상식 일시 9.10 17:30~19:00
    심사위원 판단에 따라 신청 분야 변경 가능
    선정 혜택 기업설명회 기회 제공
    """
    incomplete = _build_official_facts({"evaluation_criteria": ["배점 미공개"]})

    assert _missing_announcement_details(source, incomplete) == [
        "평가 기준과 배점",
        "평가일",
        "결과 발표일",
        "시상식 일시",
        "신청·심사 조건",
        "선정 혜택",
    ]
