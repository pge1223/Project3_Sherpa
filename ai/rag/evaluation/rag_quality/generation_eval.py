# 작성자: 용준/Claude(2026-07-22)
# 목적: 실제 페르소나 회의(ai.meeting.graph.start_ideation_conversation)를 케이스별로
#       짧게(max_rounds=1) 실행해 진짜 planning_expert/dev_expert ConvMessage를 만들고,
#       그 발언이 생성될 때 실제로 evidence_lookup이 반환한 retrieved_context를 캡처해
#       judge.py로 Faithfulness/Hallucination/Persona Evidence Fit을 판정한다.
#
#       회의 그래프(ai/meeting) 자체는 전혀 수정하지 않는다 — 여기서는 그 함수를 그대로
#       호출만 한다. evidence_lookup은 make_ideation_evidence_lookup()이 만든 실제 콜백을
#       감싸기만 하고(호출 인자/반환값을 가로채 기록), 검색 로직 자체를 바꾸지 않는다.
from __future__ import annotations

import time
import uuid
from typing import Callable, Optional

from ai.rag.evaluation.rag_quality.cache import JudgeCache
from ai.rag.evaluation.rag_quality.judge import judge_faithfulness, judge_persona_fit
from ai.rag.evaluation.rag_quality.schemas import (
    GenerationAggregate,
    GenerationCaseResult,
    MessageEvalResult,
    RagEvalCase,
)
from ai.rag.orchestration.ideation_evidence_service import make_ideation_evidence_lookup
from ai.rag.role_retrieval.service import RoleAwareRetrievalService

from ._meeting_path import ensure_meeting_on_path

ensure_meeting_on_path()
from graph import start_ideation_conversation  # noqa: E402
from graph.llm import LLMCall  # noqa: E402

_MAX_ROUNDS = 1  # 케이스당 비용을 짧게 유지한다(요청: --limit과 함께 비용 제어) — 진짜
# 발언은 1라운드(안건 제시 -> 기획 최초 의견 -> 개발 검토 -> [선택적 수정] -> 진행자 정리)만
# 만들어도 Faithfulness/Persona Fit 판정에는 충분하다.


def _make_capturing_evidence_lookup(
    project_id: str, role_retrieval_service: RoleAwareRetrievalService, top_k: int
) -> tuple[Callable[[str, str], list[dict]], dict[str, list[list[dict]]]]:
    """make_ideation_evidence_lookup()이 만든 실제 콜백을 그대로 호출하되, persona_id별로
    호출 순서대로 retrieved_context를 기록해 둔다 — 이후 같은 persona_id의 메시지가
    state["messages"]에 나타나는 순서와 1:1로 대응한다(노드가 evidence_lookup을 부른 직후
    바로 그 결과로 메시지를 만들기 때문)."""
    real_lookup = make_ideation_evidence_lookup(project_id, role_retrieval_service, top_k=top_k)
    captured: dict[str, list[list[dict]]] = {"planning_expert": [], "dev_expert": []}

    def wrapped(persona_id: str, topic_query: str) -> list[dict]:
        result = real_lookup(persona_id, topic_query)
        captured.setdefault(persona_id, []).append(result)
        return result

    return wrapped, captured


def _check_forbidden_claims(content: str, forbidden_claims: list[str]) -> list[str]:
    """forbidden_claims는 LLM 판정이 아니라 결정적 부분 문자열 매칭으로 확인한다 —
    "이런 표현이 나오면 안 된다"는 검증은 판정자 재량이 아니라 명확한 금칙어 검사이기
    때문이다."""
    return [claim for claim in forbidden_claims if claim and claim in content]


def run_generation_eval(
    cases: list[RagEvalCase],
    *,
    llm_call: LLMCall,
    judge_llm_call: LLMCall,
    judge_model: str,
    role_retrieval_service: RoleAwareRetrievalService,
    top_k: int = 5,
    cache: Optional[JudgeCache] = None,
) -> list[GenerationCaseResult]:
    results: list[GenerationCaseResult] = []

    for case in cases:
        wrapped_lookup, captured = _make_capturing_evidence_lookup(
            case.filters.project_id, role_retrieval_service, top_k
        )
        started = time.perf_counter()
        try:
            state = start_ideation_conversation(
                session_id=f"RAG-EVAL-{uuid.uuid4().hex[:8]}",
                notice_and_criteria={
                    "competition_name": "RAG 품질 평가용 세션",
                    "notice_document": "이 세션은 RAG 품질 오프라인 평가 도구가 생성한 것입니다.",
                },
                user_idea={"description": case.query},
                llm_call=llm_call,
                max_rounds=_MAX_ROUNDS,
                evidence_lookup=wrapped_lookup,
            )
        except Exception as exc:  # noqa: BLE001 - 평가 도구는 한 케이스 실패로 전체를 죽이지 않는다
            results.append(
                GenerationCaseResult(
                    case_id=case.id,
                    query=case.query,
                    generation_error=str(exc),
                    generation_time_ms=(time.perf_counter() - started) * 1000,
                )
            )
            continue
        elapsed_ms = (time.perf_counter() - started) * 1000

        persona_cursor = {"planning_expert": 0, "dev_expert": 0}
        message_results: list[MessageEvalResult] = []
        for message in state.get("messages", []):
            persona_id = message.get("speaker_id")
            if persona_id not in ("planning_expert", "dev_expert"):
                continue
            idx = persona_cursor[persona_id]
            persona_cursor[persona_id] += 1
            retrieved_context = captured.get(persona_id, [])
            context_for_message = retrieved_context[idx] if idx < len(retrieved_context) else []

            content = message.get("content", "")
            claims, faith_error = judge_faithfulness(
                judge_llm_call,
                model=judge_model,
                persona_id=persona_id,
                statement_content=content,
                retrieved_context=context_for_message,
                cache=cache,
            )
            persona_fit, fit_error = judge_persona_fit(
                judge_llm_call,
                model=judge_model,
                persona_id=persona_id,
                message_id=message.get("message_id", ""),
                statement_content=content,
                retrieved_context=context_for_message,
                cache=cache,
            )

            scorable = [c for c in claims if c.verdict != "non_factual"]
            supported = sum(1 for c in scorable if c.verdict == "supported")
            partial = sum(1 for c in scorable if c.verdict == "partially_supported")
            unsupported = sum(1 for c in scorable if c.verdict == "unsupported")
            contradicted = sum(1 for c in scorable if c.verdict == "contradicted")
            denom = supported + partial + unsupported + contradicted

            message_results.append(
                MessageEvalResult(
                    case_id=case.id,
                    message_id=message.get("message_id", ""),
                    persona_id=persona_id,  # type: ignore[arg-type]
                    round=message.get("round", 1),
                    content_preview=content[:200],
                    claims=claims,
                    faithfulness_score=((supported + 0.5 * partial) / denom) if denom else None,
                    hallucination_rate=((unsupported + contradicted) / denom) if denom else None,
                    unsupported_count=unsupported,
                    contradicted_count=contradicted,
                    non_factual_count=len(claims) - len(scorable),
                    forbidden_claim_hits=_check_forbidden_claims(content, case.forbidden_claims),
                    persona_fit=persona_fit,
                    judge_error=faith_error or fit_error,
                )
            )

        results.append(
            GenerationCaseResult(
                case_id=case.id,
                query=case.query,
                messages=message_results,
                generation_time_ms=elapsed_ms,
            )
        )

    return results


def aggregate_generation(results: list[GenerationCaseResult]) -> GenerationAggregate:
    all_messages = [m for r in results for m in r.messages]
    scored_faith = [m.faithfulness_score for m in all_messages if m.faithfulness_score is not None]
    scored_halluc = [m.hallucination_rate for m in all_messages if m.hallucination_rate is not None]
    scored_fit = [m.persona_fit.normalized_score for m in all_messages if m.persona_fit is not None]
    failed_generations = [r for r in results if r.generation_error is not None]
    failed_judges = [m for m in all_messages if m.judge_error is not None]

    def _mean(values: list[float]) -> Optional[float]:
        return sum(values) / len(values) if values else None

    fit_macro = _mean(scored_fit)
    severe = [
        f"{m.case_id}/{m.message_id}: {c.claim} ({c.verdict})"
        for m in all_messages
        for c in m.claims
        if c.verdict == "contradicted"
    ][:10]

    return GenerationAggregate(
        case_count=len(results),
        message_count=len(all_messages),
        faithfulness_macro=_mean(scored_faith),
        hallucination_rate_macro=_mean(scored_halluc),
        persona_evidence_fit_macro=fit_macro,
        persona_evidence_fit_percent=(fit_macro * 100 if fit_macro is not None else None),
        generation_failure_rate=(len(failed_generations) / len(results)) if results else None,
        eval_failure_rate=(len(failed_judges) / len(all_messages)) if all_messages else None,
        avg_generation_time_ms=_mean([r.generation_time_ms for r in results]) or 0.0,
        severe_hallucination_examples=severe,
    )
