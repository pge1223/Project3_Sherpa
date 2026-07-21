# 작성자: 경이
# 목적: 위원(raw)·위원장(raw) LLM 출력을 review_output.schema.json v2의
#       reviewerResult / chairSummary / revision 구조로 변환한다(M4). reviewer_prompt.txt·
#       chair_prompt.txt의 원본 출력 스키마는 가은 기획 초안을 그대로 유지하고, v2 계약
#       변환은 이 모듈이 전담한다 — reviewer/chair raw 스키마를 v2에 맞춰 고치지 않기로 한
#       기존 결정(devlog 2026-07-14)을 그대로 따른다.
# import: 같은 패키지의 evidence.EvidencePool.

from __future__ import annotations

from typing import Any

from .evidence import EvidencePool

# reviewer_prompt.txt의 judgment(6종) -> v2 rubricScore.judgment(4종).
# insufficient_evidence/not_applicable은 score_recommendation이 null이라 애초에 rubric_scores에서
# 제외한다(_UNSCORABLE_JUDGMENTS) — 그 결과 이 기준은 '아무도 채점하지 않은 것'이 되고,
# M2 scoring(ai/meeting/scoring)의 필수항목 누락 감점(MTG-003) 로직이 그대로 처리한다.
_JUDGMENT_MAP = {
    "strong": "strong",
    "adequate": "acceptable",
    "needs_improvement": "needs_improvement",
    "critical_risk": "critical_risk",
}
_UNSCORABLE_JUDGMENTS = {"insufficient_evidence", "not_applicable"}

# reviewer_prompt.txt의 cross_reviews.relation(agree|supplement|disagree)
# -> v2 crossReview.relation(supplement|challenge|support).
_CROSS_REVIEW_RELATION_MAP = {"agree": "support", "supplement": "supplement", "disagree": "challenge"}

_CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}


def _evidence_status(evidence_refs: list[dict], confidence: str) -> str:
    """rubricScore.evidence_status는 raw 스키마에 없는 필드라 evidence_refs 개수와
    항목 confidence로 보수적으로 유도한다: 근거 없음=insufficient, high 신뢰도=sufficient,
    그 외(근거는 있지만 medium/low 신뢰도)=partial."""
    if not evidence_refs:
        return "insufficient"
    if confidence == "high":
        return "sufficient"
    return "partial"


def _overall_confidence(review_items: list[dict]) -> str:
    """reviewerResult.confidence(전체 1개)는 raw에 없어 review_items별 confidence 중
    가장 낮은 값을 대표값으로 삼는다(보수적 집계)."""
    confidences = [item.get("confidence", "medium") for item in review_items]
    if not confidences:
        return "medium"
    return min(confidences, key=lambda c: _CONFIDENCE_ORDER.get(c, 1))


def raw_reviewer_to_v2(
    raw: dict[str, Any],
    evidence_pool: EvidencePool,
    criterion_evidence: dict[str, dict] | None = None,
) -> dict[str, Any]:
    """reviewer_prompt.txt 출력(raw) 한 건을 review_output.schema.json v2의 reviewerResult로 변환한다.

    criterion_evidence가 주어지면(A안, RAG-004/005 경로) criterion_id -> {linked_evidence_refs,
    sufficiency}로: ①최종 sufficiency.allow_numeric_score=False인 항목은 미채점 처리하고(누락
    경로로 흘려보냄), ②근거(evidence_ids)는 위원 자기보고 대신 linked_evidence_refs로 발급한다.
    None이면(레거시) 위원 자기보고 evidence_refs를 그대로 등록한다.

    재인/Claude(2026-07-21, 사용자 확인 하에 진행 — review_output.schema.json v2.3.0):
    지금까지는 위 두 경로(judgment가 insufficient_evidence/not_applicable이거나, RAG 게이트가
    막은 경우) 모두 그냥 continue로 조용히 버려서, "이 항목이 왜 없는지"가 어디에도 안 남았다
    (워크벤치 화면에서 실측 확인 — 사용자가 항목이 통째로 사라진 이유를 알 방법이 없었음).
    이제 unscored_criteria에 그 이유를 남긴다 - GPT가 review_items에 그 criterion_id 자체를
    아예 안 넣은 경우(위원 응답 누락, 별도 이슈)는 raw에 없으니 애초에 이 루프를 안 거쳐서
    unscored_criteria에도 안 남는다 - 그래서 "위원이 시도는 했지만 못 채점" vs "위원이 그
    항목을 아예 언급 안 함"을 rubric.criteria와 대조하면 구분할 수 있다(후자는 rubric_scores에도
    unscored_criteria에도 없는 criterion_id).
    """
    review_items = raw.get("review_items", [])
    rubric_scores = []
    unscored_criteria = []
    for item in review_items:
        cid = item["criterion_id"]
        judgment = item["judgment"]
        if judgment in _UNSCORABLE_JUDGMENTS:
            unscored_criteria.append(
                {
                    "criterion_id": cid,
                    "criterion_name": item["criterion_name"],
                    "reason": judgment,
                }
            )
            continue

        if criterion_evidence is not None:
            ce = criterion_evidence.get(cid)
            # 게이팅: 최종 근거충족도가 숫자 점수를 허용하지 않으면 미채점(그 (persona,criterion)만 제외)
            if ce is None or not ce.get("sufficiency", {}).get("allow_numeric_score", False):
                unscored_criteria.append(
                    {
                        "criterion_id": cid,
                        "criterion_name": item["criterion_name"],
                        "reason": "evidence_gate_blocked",
                        "attempted_judgment": _JUDGMENT_MAP[judgment],
                        "strengths": item.get("strengths", []),
                        "weaknesses": item.get("weaknesses", []),
                    }
                )
                continue
            linked_refs = ce.get("linked_evidence_refs", [])
            evidence_ids = [evidence_pool.register_linked(r) for r in linked_refs]
            evidence_status = "sufficient"
        else:
            evidence_refs = item.get("evidence_refs", [])
            evidence_ids = [evidence_pool.register(ref) for ref in evidence_refs]
            evidence_status = _evidence_status(evidence_refs, item.get("confidence", "medium"))

        rubric_scores.append(
            {
                "criterion_id": cid,
                "criterion_name": item["criterion_name"],
                "score": item["score_recommendation"],
                "max_score": item["max_score"],
                "judgment": _JUDGMENT_MAP[judgment],
                "strengths": item.get("strengths", []),
                "issues": item.get("weaknesses", []),
                "suggestions": item.get("improvement_actions", []),
                "evidence_ids": evidence_ids,
                "evidence_status": evidence_status,
            }
        )

    persona_name = raw.get("persona_name", raw["persona_id"])
    result: dict[str, Any] = {
        "review_id": raw["review_id"],
        "persona_id": raw["persona_id"],
        "persona_name": persona_name,
        "role": persona_name,
        "review_round": raw.get("review_round", 1),
        "summary": raw.get("review_summary", ""),
        "rubric_scores": rubric_scores,
        "confidence": _overall_confidence(review_items),
    }
    if unscored_criteria:
        result["unscored_criteria"] = unscored_criteria

    cross_reviews = [
        {
            "target_persona_id": cr["target_persona_id"],
            "relation": _CROSS_REVIEW_RELATION_MAP[cr["relation"]],
            "target_criterion_id": cr.get("target_criterion_id"),
            "comment": cr["comment"],
            "evidence_ids": [evidence_pool.register(ref) for ref in cr.get("evidence_refs", [])],
        }
        for cr in raw.get("cross_reviews", [])
    ]
    if cross_reviews:
        result["cross_reviews"] = cross_reviews

    out_of_scope = raw.get("out_of_scope", [])
    if out_of_scope:
        result["out_of_scope"] = out_of_scope

    return result


def raw_chair_to_v2(raw: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """chair_prompt.txt 출력(raw)을 v2 chair_summary, top_revisions로 변환한다."""
    chair_summary = {
        "chair_id": raw.get("chair_id", "review_chair"),
        "overall_assessment": raw["overall_assessment"],
        "consensus": raw.get("consensus", []),
        "disagreements": raw.get("disagreements", []),
        "top_strengths": raw.get("top_strengths", []),
        "top_risks": raw.get("top_risks", []),
        "final_decision": raw.get("final_decision"),
        "decision_note": raw.get("decision_note"),
    }
    top_revisions = [
        {
            "priority": action["priority"],
            "title": action["title"],
            "reason": action["reason"],
            "target": action["target"],
            "action": action["action"],
            "related_criteria": action.get("related_criteria", []),
            "evidence_ids": action.get("evidence_ids", []),
        }
        for action in raw.get("final_priority_actions", [])[:5]
    ]
    return chair_summary, top_revisions
