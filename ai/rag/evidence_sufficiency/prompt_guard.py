"""
Prompt Guard Templates (RAG-005)
=====================================
상태별로 회의 위원 프롬프트에 그대로 삽입할 수 있는 정적 안전 안내문을 만든다.
LLM을 호출하지 않는다 — 순수 문자열 템플릿이다.
"""

from ai.rag.evidence_sufficiency.schemas import EvidenceSufficiencyStatus

_SUFFICIENT_GUARD = (
    "검색된 문서 근거 범위 안에서만 평가하세요. "
    "근거에 없는 사실이나 수치를 임의로 추가하지 마세요. "
    "사용한 근거를 명확히 표시하세요."
)

_PARTIAL_GUARD = (
    "관련 근거가 일부만 확인되었습니다. "
    "확인된 근거 범위 안에서 제한적으로 평가하고, "
    "확인되지 않은 사실이나 수치를 단정하지 마세요. "
    "근거가 부족한 평가 항목과 추가로 필요한 자료를 명시하세요. "
    "확정적인 점수는 생성하지 마세요."
)

_INSUFFICIENT_GUARD = (
    "평가에 필요한 관련 문서 근거가 부족합니다. "
    "확인되지 않은 사실, 수치, 위험 요소를 추측하지 마세요. "
    "확정적인 평가 점수나 합격·불합격 판단을 생성하지 마세요. "
    "현재 부족한 근거와 추가로 필요한 자료만 명시하세요."
)

_GUARD_BY_STATUS: dict[EvidenceSufficiencyStatus, str] = {
    EvidenceSufficiencyStatus.SUFFICIENT: _SUFFICIENT_GUARD,
    EvidenceSufficiencyStatus.PARTIAL: _PARTIAL_GUARD,
    EvidenceSufficiencyStatus.INSUFFICIENT: _INSUFFICIENT_GUARD,
}


def build_prompt_guard(status: EvidenceSufficiencyStatus) -> str:
    """상태에 대응하는 정적 안전 안내문을 반환한다."""
    return _GUARD_BY_STATUS[status]


__all__ = ["build_prompt_guard"]
