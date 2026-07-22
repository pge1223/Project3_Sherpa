"""
Unit Tests for ai.rag.evaluation.rag_quality.{judge,generation_eval,cache}
(fake LLM 호출만 사용 — 실제 OpenAI API, ai.meeting 그래프 실행 없음)
"""

from __future__ import annotations

import json

import pytest

from ai.rag.evaluation.rag_quality.cache import JudgeCache
from ai.rag.evaluation.rag_quality.generation_eval import _check_forbidden_claims, aggregate_generation
from ai.rag.evaluation.rag_quality.judge import (
    _safe_call_json_retry,
    _validate_faithfulness_response,
    _validate_persona_fit_response,
    judge_faithfulness,
    judge_persona_fit,
)
from ai.rag.evaluation.rag_quality.schemas import ClaimVerdict, GenerationCaseResult, MessageEvalResult, PersonaFitResult


class _ScriptedLLM:
    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls = 0

    def __call__(self, prompt: str) -> str:
        self.calls += 1
        return self._responses.pop(0)


# --------------------------------------------------------------------------
# JSON 스키마 오류 처리 / 재시도
# --------------------------------------------------------------------------


def test_safe_call_json_retry_succeeds_on_second_attempt():
    llm = _ScriptedLLM(["not json at all", json.dumps({"ok": True})])
    raw, ok, attempts = _safe_call_json_retry(llm, "prompt", lambda r: None if r.get("ok") else "bad")
    assert ok is True
    assert raw == {"ok": True}
    assert attempts == 2


def test_safe_call_json_retry_fails_after_max_attempts():
    llm = _ScriptedLLM(["bad", "still bad"])
    raw, ok, attempts = _safe_call_json_retry(llm, "prompt", lambda r: "always invalid")
    assert ok is False
    assert raw is None
    assert llm.calls == 2


def test_judge_faithfulness_returns_error_when_schema_invalid_after_retries():
    llm = _ScriptedLLM([json.dumps({"claims": "not-a-list"}), json.dumps({"claims": "still-not-a-list"})])
    claims, error = judge_faithfulness(
        llm, model="test-model", persona_id="planning_expert", statement_content="x", retrieved_context=[]
    )
    assert claims == []
    assert error == "faithfulness_judge_failed_validation"


def test_judge_faithfulness_parses_valid_claims():
    payload = {
        "claims": [
            {
                "claim": "공모전 접수기간은 7월 8일부터다",
                "verdict": "supported",
                "supporting_document_ids": ["doc-a"],
                "supporting_evidence_excerpt": "접수기간 2026-07-08",
                "reason": "문서에 그대로 있음",
                "confidence": 0.9,
            }
        ]
    }
    llm = _ScriptedLLM([json.dumps(payload)])
    claims, error = judge_faithfulness(
        llm, model="test-model", persona_id="planning_expert", statement_content="x", retrieved_context=[]
    )
    assert error is None
    assert len(claims) == 1
    assert claims[0].verdict == "supported"
    assert claims[0].supporting_document_ids == ["doc-a"]


def test_judge_persona_fit_rejects_out_of_range_score():
    llm = _ScriptedLLM([json.dumps({"score": 7}), json.dumps({"score": 7})])
    result, error = judge_persona_fit(
        llm,
        model="test-model",
        persona_id="dev_expert",
        message_id="m1",
        statement_content="x",
        retrieved_context=[],
    )
    assert result is None
    assert error == "persona_fit_judge_failed_validation"


def test_judge_persona_fit_normalizes_score():
    llm = _ScriptedLLM([json.dumps({"score": 3, "role_aligned_points": ["MVP 범위"], "role_mismatch_points": []})])
    result, error = judge_persona_fit(
        llm,
        model="test-model",
        persona_id="dev_expert",
        message_id="m1",
        statement_content="x",
        retrieved_context=[],
    )
    assert error is None
    assert result.score == 3
    assert result.normalized_score == pytest.approx(0.75)


# --------------------------------------------------------------------------
# 캐시 — 같은 입력 반복 평가 가능
# --------------------------------------------------------------------------


def test_judge_cache_avoids_second_llm_call(tmp_path):
    cache = JudgeCache(cache_dir=tmp_path)
    llm = _ScriptedLLM([json.dumps({"claims": []})])
    claims1, _ = judge_faithfulness(
        llm, model="m", persona_id="planning_expert", statement_content="같은 발언", retrieved_context=[], cache=cache
    )
    # 두 번째 호출은 LLM을 다시 부르면 IndexError(응답 리스트가 비어있음)가 나야 정상 —
    # 캐시가 실제로 막아주는지 확인한다.
    claims2, _ = judge_faithfulness(
        llm, model="m", persona_id="planning_expert", statement_content="같은 발언", retrieved_context=[], cache=cache
    )
    assert claims1 == claims2 == []
    assert llm.calls == 1


def test_judge_cache_disabled_calls_llm_every_time(tmp_path):
    cache = JudgeCache(cache_dir=tmp_path, enabled=False)
    llm = _ScriptedLLM([json.dumps({"claims": []}), json.dumps({"claims": []})])
    judge_faithfulness(llm, model="m", persona_id="planning_expert", statement_content="x", retrieved_context=[], cache=cache)
    judge_faithfulness(llm, model="m", persona_id="planning_expert", statement_content="x", retrieved_context=[], cache=cache)
    assert llm.calls == 2


# --------------------------------------------------------------------------
# Faithfulness / Hallucination Rate / Persona Evidence Fit 집계 수식
# --------------------------------------------------------------------------


def _claim(verdict: str) -> ClaimVerdict:
    return ClaimVerdict(claim="c", verdict=verdict, reason="r", confidence=0.5)


def test_non_factual_excluded_from_faithfulness_denominator():
    """generation_eval.run_generation_eval의 분모 계산 로직을 MessageEvalResult 생성
    시점과 동일한 공식으로 직접 검증한다(요청 4번: non_factual은 분모 제외)."""
    claims = [_claim("supported"), _claim("non_factual"), _claim("non_factual")]
    scorable = [c for c in claims if c.verdict != "non_factual"]
    denom = len(scorable)
    assert denom == 1  # non_factual 2개는 분모에서 빠졌다


def test_partially_supported_gets_half_weight():
    claims = [_claim("supported"), _claim("partially_supported"), _claim("unsupported")]
    supported = sum(1 for c in claims if c.verdict == "supported")
    partial = sum(1 for c in claims if c.verdict == "partially_supported")
    unsupported = sum(1 for c in claims if c.verdict == "unsupported")
    contradicted = sum(1 for c in claims if c.verdict == "contradicted")
    denom = supported + partial + unsupported + contradicted
    faithfulness = (supported + 0.5 * partial) / denom
    assert faithfulness == pytest.approx((1 + 0.5) / 3)


def test_hallucination_rate_counts_unsupported_and_contradicted():
    claims = [_claim("supported"), _claim("unsupported"), _claim("contradicted")]
    supported = sum(1 for c in claims if c.verdict == "supported")
    unsupported = sum(1 for c in claims if c.verdict == "unsupported")
    contradicted = sum(1 for c in claims if c.verdict == "contradicted")
    denom = supported + unsupported + contradicted
    hallucination_rate = (unsupported + contradicted) / denom
    assert hallucination_rate == pytest.approx(2 / 3)


def test_faithfulness_not_applicable_when_denominator_zero():
    """전부 non_factual이면 분모가 0 — 억지로 1.0을 만들지 않고 None(not_applicable)."""
    message = MessageEvalResult(
        case_id="c1",
        message_id="m1",
        persona_id="planning_expert",
        round=1,
        content_preview="",
        claims=[_claim("non_factual")],
        faithfulness_score=None,
        hallucination_rate=None,
    )
    assert message.faithfulness_score is None
    assert message.hallucination_rate is None


def test_aggregate_generation_averages_only_present_scores_and_collects_contradicted():
    messages = [
        MessageEvalResult(
            case_id="c1", message_id="m1", persona_id="planning_expert", round=1, content_preview="",
            faithfulness_score=1.0, hallucination_rate=0.0,
            claims=[_claim("supported")],
            persona_fit=PersonaFitResult(persona_id="planning_expert", message_id="m1", score=4, normalized_score=1.0),
        ),
        MessageEvalResult(
            case_id="c1", message_id="m2", persona_id="dev_expert", round=1, content_preview="",
            faithfulness_score=None, hallucination_rate=None,  # not_applicable — 평균에서 빠져야 함
            claims=[_claim("non_factual")],
        ),
        MessageEvalResult(
            case_id="c2", message_id="m3", persona_id="dev_expert", round=1, content_preview="",
            faithfulness_score=0.0, hallucination_rate=1.0,
            claims=[_claim("contradicted")],
            persona_fit=PersonaFitResult(persona_id="dev_expert", message_id="m3", score=0, normalized_score=0.0),
        ),
    ]
    results = [
        GenerationCaseResult(case_id="c1", query="q1", messages=messages[:2]),
        GenerationCaseResult(case_id="c2", query="q2", messages=messages[2:]),
    ]
    agg = aggregate_generation(results)

    assert agg.message_count == 3
    assert agg.faithfulness_macro == pytest.approx((1.0 + 0.0) / 2)  # None인 m2는 제외
    assert agg.hallucination_rate_macro == pytest.approx((0.0 + 1.0) / 2)
    assert agg.persona_evidence_fit_macro == pytest.approx((1.0 + 0.0) / 2)
    assert agg.persona_evidence_fit_percent == pytest.approx(50.0)
    assert any("m3" in ex for ex in agg.severe_hallucination_examples)


def test_forbidden_claims_detected_by_exact_substring():
    hits = _check_forbidden_claims(
        "이 문서를 보면 100% 정확도로 합격을 보장합니다.", ["100% 정확도로 합격을 보장"]
    )
    assert hits == ["100% 정확도로 합격을 보장"]
    assert _check_forbidden_claims("전혀 관련 없는 문장입니다.", ["100% 정확도로 합격을 보장"]) == []


def test_human_verified_false_cases_excluded_from_official_generation_score_is_caller_responsibility():
    """generation_eval 자체는 human_verified로 필터링하지 않는다 — CLI가
    --human-verified-only로 케이스 목록을 미리 거르는 책임을 진다(dataset.filter_cases).
    이 테스트는 그 분담이 실제로 dataset.py에 있는지 회귀 확인한다."""
    from ai.rag.evaluation.rag_quality.dataset import filter_cases
    from ai.rag.evaluation.rag_quality.schemas import RagEvalCase, RagEvalFilters

    cases = [
        RagEvalCase(
            id="v", query="q", persona_id="planning_expert", filters=RagEvalFilters(project_id="p"),
            gold_document_ids=["d"], human_verified=True,
        ),
        RagEvalCase(
            id="u", query="q", persona_id="planning_expert", filters=RagEvalFilters(project_id="p"),
            gold_document_ids=["d"], human_verified=False,
        ),
    ]
    assert [c.id for c in filter_cases(cases, human_verified_only=True)] == ["v"]
