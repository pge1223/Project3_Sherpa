# 작성자: 용준/Claude(2026-07-23, Phase 2 "Active Evidence Injection")
# 목적: _evidence_planner_for(use_rag)가 새 ENABLE_IDEATION_EVIDENCE_PLANNER_DISCUSSION
#       플래그를 SHADOW 플래그와 독립적으로 해석하고, 반환하는 콜러블의 active 속성을
#       정확히 세팅하는지 검증한다(요청: "기존 ENABLE_IDEATION_EVIDENCE_PLANNER_SHADOW와
#       분리할 것"). 실제 plan 선택 로직은 ai/rag/tests/test_ideation_evidence_planner.py가,
#       active 모드로 실제 prompt/grounding에 반영되는지는
#       ai/meeting/tests/test_ideation_evidence_planner_active.py가 검증한다 — 여기서는
#       "언제 콜러블을 만들고 active를 True/False로 세팅하는가"라는 backend 레이어의 배선만
#       확인한다.

from app.api.routes.ideation_conversation_preview import _evidence_planner_for
from app.config import settings


def _reset_flags():
    settings.ENABLE_IDEATION_EVIDENCE_PLANNER_SHADOW = False
    settings.ENABLE_IDEATION_EVIDENCE_PLANNER_DISCUSSION = False


def test_both_flags_off_returns_none():
    _reset_flags()
    try:
        assert _evidence_planner_for(use_rag=True) is None
    finally:
        _reset_flags()


def test_use_rag_false_returns_none_even_if_flags_on():
    _reset_flags()
    settings.ENABLE_IDEATION_EVIDENCE_PLANNER_SHADOW = True
    settings.ENABLE_IDEATION_EVIDENCE_PLANNER_DISCUSSION = True
    try:
        assert _evidence_planner_for(use_rag=False) is None
    finally:
        _reset_flags()


def test_shadow_only_returns_planner_with_active_false():
    _reset_flags()
    settings.ENABLE_IDEATION_EVIDENCE_PLANNER_SHADOW = True
    try:
        planner = _evidence_planner_for(use_rag=True)
        assert planner is not None
        assert planner.active is False
    finally:
        _reset_flags()


def test_discussion_flag_returns_planner_with_active_true():
    _reset_flags()
    settings.ENABLE_IDEATION_EVIDENCE_PLANNER_DISCUSSION = True
    try:
        planner = _evidence_planner_for(use_rag=True)
        assert planner is not None
        assert planner.active is True
    finally:
        _reset_flags()


def test_both_flags_on_still_returns_single_planner_callable_with_active_true():
    """요청: "active와 shadow가 동시에 켜져도 Planner를 중복 실행하지 말 것" — backend 레이어
    관점에서는 이 요청이 "콜러블을 두 번 만들거나 두 개 주입하지 않는다"로 나타난다. 실제
    "턴당 한 번만 호출"은 ai/meeting/graph/ideation_conv_nodes.py::_run_shadow_evidence_planner가
    유일한 호출 지점이라는 구조로 보장된다(다른 테스트가 검증)."""
    _reset_flags()
    settings.ENABLE_IDEATION_EVIDENCE_PLANNER_SHADOW = True
    settings.ENABLE_IDEATION_EVIDENCE_PLANNER_DISCUSSION = True
    try:
        planner = _evidence_planner_for(use_rag=True)
        assert planner is not None
        assert planner.active is True
    finally:
        _reset_flags()
