# 작성자: 가은/Claude(2026-07-22, 요청: "(20)" 배점 지어내기 버그 수정)
# 목적: _build_announcement_analysis_prompt가 "평가 항목 개수로 배점을 역산해서 지어내지
#       말 것"을 명시하는지 검증한다. 실측: WSCE2026 신청서 양식 PDF(원문에 배점 숫자가
#       전혀 없음, 항목 5개씩 두 부문)를 분석했더니 evaluation_criteria가 "혁신성 (20)"처럼
#       100점을 5등분한 값을 지어내 붙였다 — 프롬프트의 기존 "배점이 없으면 배점 미공개로
#       남기라"는 규칙이 "항목 개수로 배점을 계산해 붙이는 것"까지는 명시적으로 막지
#       않았기 때문이다. LLM 응답 자체는 결정적으로 테스트할 수 없으므로(모델 샘플링),
#       여기서는 프롬프트에 그 금지 규칙이 실제로 포함되는지만 확인한다.
# import: 표준 라이브러리 없음; app.api.routes.documents.

import app.api.routes.documents as documents_route


def test_prompt_forbids_deriving_score_from_criteria_count():
    prompt = documents_route._build_announcement_analysis_prompt("아무 공고문 원문")
    assert "역산" in prompt
    assert "혁신성 (20)" in prompt  # 실측 사고 사례를 반례로 명시했는지
    assert "배점 미공개" in prompt  # 기존 규칙도 그대로 남아있는지
