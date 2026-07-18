# 작성자: 가은/Claude(2026-07-19)
# 목적: STEP7 대화형 피드백에서 "위원장이 질문마다 같은 우선순위(KPI 등)만 반복 인용한다"는
#       실사용 지적 대응 — _build_followup_prompt()가 매번 top_revisions를 1순위부터 그대로
#       주다 보니 모델이 항상 같은 항목으로 돌아가던 문제를 고치기 위해 추가한
#       _reorder_unmentioned_revisions_first()/_keywords()를 검증한다. LLM 호출 없이
#       순수 함수만 테스트한다(app.main import 시 KURE 임베더 등이 로딩되므로 다소 느릴 수
#       있음 — 기존 backend/tests 컨벤션과 동일).
# import: 표준 라이브러리 없음(pytest만); app.api.routes.meetings의 순수 함수.

from app.api.routes.meetings import _keywords, _reorder_unmentioned_revisions_first


def _revision(title: str, priority: int) -> dict:
    return {"priority": priority, "title": title, "reason": "r", "target": "t", "action": "a"}


def test_keywords_drops_short_tokens_and_stopwords():
    kws = _keywords("KPI 및 정량적 효과 구체화")
    assert "KPI" in kws
    assert "정량적" in kws
    assert "효과" in kws
    assert "구체화" in kws
    assert "및" not in kws  # 불용어 제외


def test_no_history_returns_original_order():
    revisions = [_revision("KPI 구체화", 1), _revision("차별성 근거 보강", 2)]
    assert _reorder_unmentioned_revisions_first(revisions, None) == revisions
    assert _reorder_unmentioned_revisions_first(revisions, []) == revisions


def test_already_discussed_revision_is_deprioritized():
    """실측 재현: top_revisions[0]이 KPI 관련 항목이고, 이전 답변에서 이미 KPI/정량적
    효과를 충분히 얘기했다면 다음 호출에선 그 항목이 뒤로 밀려야 한다."""
    revisions = [
        _revision("KPI 및 정량적 효과 구체화", 1),
        _revision("차별화 근거 보강", 2),
        _revision("전달력 흐름 개선", 3),
    ]
    history = [
        {
            "question": "가장 시급한 건 뭔가요?",
            "answer": "매출 증가액과 이용자 편익에 대한 구체적인 KPI와 정량적 효과 수치를 제시하는 것이 가장 시급합니다.",
        }
    ]

    reordered = _reorder_unmentioned_revisions_first(revisions, history)

    assert reordered[0]["title"] == "차별화 근거 보강"
    assert reordered[-1]["title"] == "KPI 및 정량적 효과 구체화"


def test_unrelated_history_does_not_reorder():
    revisions = [
        _revision("KPI 및 정량적 효과 구체화", 1),
        _revision("차별화 근거 보강", 2),
    ]
    history = [{"question": "제출 서류가 뭔가요?", "answer": "사업계획서와 재무제표가 필요합니다."}]

    reordered = _reorder_unmentioned_revisions_first(revisions, history)

    assert reordered == revisions  # 관련 없는 대화면 순서 유지


def test_multiple_mentioned_items_all_move_to_back_in_original_relative_order():
    revisions = [
        _revision("KPI 구체화", 1),
        _revision("차별화 근거 보강", 2),
        _revision("전달력 흐름 개선", 3),
    ]
    history = [
        {
            "question": "q1",
            "answer": "KPI를 구체화하고, 전달력 흐름도 개선하면 좋겠습니다.",
        }
    ]

    reordered = _reorder_unmentioned_revisions_first(revisions, history)

    assert [r["title"] for r in reordered] == ["차별화 근거 보강", "KPI 구체화", "전달력 흐름 개선"]


def test_empty_top_revisions_returns_as_is():
    assert _reorder_unmentioned_revisions_first([], [{"question": "q", "answer": "a"}]) == []
    assert _reorder_unmentioned_revisions_first(None, [{"question": "q", "answer": "a"}]) is None
