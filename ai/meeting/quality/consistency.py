# 작성자: 경이
# 목적: 위원 일관성 테스트 하네스(TST-002). 같은 문서를 반복 평가했을 때 항목별 점수·판단·
#       핵심 지적이 허용 편차 안에서 일관되는지 측정한다. 생성 모델은 완전 동일 출력을
#       보장하지 않으므로(예외사항 "완전 동일 요구 금지"), '완전 일치'가 아니라 '허용 편차
#       정의 + 편차 측정'으로 검수한다. 실제 LLM 연동 전에는 stub으로 파이프라인 자체의
#       결정론(동일 LLM 출력 → 동일 결과)을 baseline으로 확인하고, 실제 모델이 붙으면 같은
#       하네스로 편차를 측정한다.
# import: 표준 라이브러리 dataclasses/statistics/collections/itertools/typing. (외부 의존성 없음)
#         입력은 review_output.schema.json v2 문서(dict) 목록이라 회의 코드에 의존하지 않는다.

from __future__ import annotations

import itertools
import statistics
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ConsistencyTolerance:
    """반복 평가 편차 허용 범위(검수 기준 "점수 편차 허용범위 정의").

    실제 모델·도메인에 맞춰 조정한다 — 기본값은 100점 만점 기준의 보수적 시작값이다.
    """

    max_total_score_range: float = 10.0  # 총점 (최대-최소) 허용 폭
    max_criterion_score_range: float = 8.0  # 항목별 점수 (최대-최소) 허용 폭
    min_judgment_agreement: float = 0.6  # 항목별 최빈 judgment 일치 비율 하한
    min_key_issue_jaccard: float = 0.3  # 핵심 지적 집합 평균 Jaccard 하한


def _extract(document: dict[str, Any]) -> dict[str, Any]:
    """v2 문서 1건에서 일관성 측정에 필요한 값만 뽑는다."""
    score_result = document.get("score_result") or {}
    total = score_result.get("total_score", 0)
    scores = {b["criterion_id"]: b["raw_score"] for b in score_result.get("breakdown", [])}

    judgments: dict[str, list[str]] = defaultdict(list)
    issues: set[str] = set()
    for r in document.get("reviewer_results", []):
        for s in r.get("rubric_scores", []):
            if s.get("judgment"):
                judgments[s["criterion_id"]].append(s["judgment"])
            for issue in s.get("issues", []):
                issues.add(issue)
    # 한 항목을 여러 위원이 채점하면 판단들을 정렬해 하나의 대표 문자열로 만든다.
    judgment_repr = {cid: "|".join(sorted(js)) for cid, js in judgments.items()}
    return {"total": total, "scores": scores, "judgments": judgment_repr, "issues": issues}


def _stat(values: list[float]) -> dict[str, float]:
    return {
        "mean": statistics.mean(values),
        "stdev": statistics.pstdev(values) if len(values) > 1 else 0.0,
        "min": min(values),
        "max": max(values),
        "range": max(values) - min(values),
    }


def _mode_agreement(values: list[str]) -> tuple[str | None, float]:
    """최빈값과 그 일치 비율(최빈값 개수 / 전체)."""
    vals = [v for v in values if v is not None]
    if not vals:
        return None, 1.0
    mode, count = Counter(vals).most_common(1)[0]
    return mode, count / len(vals)


def _mean_pairwise_jaccard(sets: list[set[str]]) -> float:
    """실행 쌍마다 핵심 지적 집합의 Jaccard를 구해 평균낸다. 실행이 1건이면 1.0.

    주의: 문자열 정확 일치 기반이라 같은 지적을 다르게 표현하면 낮게 나온다 — 어휘 편차까지
    감안한 판정은 아니고 '거친 신호'로 쓴다(생성 모델 특성상 완전 동일 요구는 하지 않는다).
    """
    if len(sets) < 2:
        return 1.0
    ratios: list[float] = []
    for a, b in itertools.combinations(sets, 2):
        union = a | b
        ratios.append(1.0 if not union else len(a & b) / len(union))
    return statistics.mean(ratios)


def summarize_consistency(
    documents: list[dict[str, Any]],
    tolerance: ConsistencyTolerance | None = None,
) -> dict[str, Any]:
    """반복 평가 결과(v2 문서 목록)의 일관성 지표와 허용범위 위반 여부를 계산한다."""
    if not documents:
        raise ValueError("문서가 최소 1개는 필요합니다.")
    tol = tolerance or ConsistencyTolerance()
    n = len(documents)
    extracts = [_extract(d) for d in documents]
    violations: list[str] = []

    totals = [e["total"] for e in extracts]
    total_stat = _stat(totals)
    total_within = total_stat["range"] <= tol.max_total_score_range
    if not total_within:
        violations.append(f"총점 편차 {total_stat['range']} > 허용 {tol.max_total_score_range}")

    all_cids = sorted({cid for e in extracts for cid in e["scores"]})
    criteria: dict[str, Any] = {}
    for cid in all_cids:
        cscores = [e["scores"][cid] for e in extracts if cid in e["scores"]]
        cjudg = [e["judgments"][cid] for e in extracts if cid in e["judgments"]]
        score_stat = _stat(cscores) if cscores else None
        mode, agreement = _mode_agreement(cjudg)

        within = True
        if score_stat and score_stat["range"] > tol.max_criterion_score_range:
            within = False
            violations.append(
                f"[{cid}] 점수 편차 {score_stat['range']} > 허용 {tol.max_criterion_score_range}"
            )
        if cjudg and agreement < tol.min_judgment_agreement:
            within = False
            violations.append(
                f"[{cid}] judgment 일치율 {agreement:.2f} < 허용 {tol.min_judgment_agreement}"
            )

        criteria[cid] = {
            "score": score_stat,
            "scored_ratio": len(cscores) / n,  # 게이팅/누락으로 채점 여부가 실행마다 갈리는지(정보용)
            "judgment_mode": mode,
            "judgment_agreement": agreement,
            "within_tolerance": within,
        }

    jaccard = _mean_pairwise_jaccard([e["issues"] for e in extracts])
    if jaccard < tol.min_key_issue_jaccard:
        violations.append(f"핵심 지적 평균 Jaccard {jaccard:.2f} < 허용 {tol.min_key_issue_jaccard}")

    return {
        "n_runs": n,
        "total_score": {**total_stat, "within_tolerance": total_within},
        "criteria": criteria,
        "key_issue_jaccard_mean": jaccard,
        "within_tolerance": len(violations) == 0,
        "violations": violations,
        "tolerance": asdict(tol),
    }


def run_consistency_check(
    run_fn: Callable[[], dict[str, Any]],
    n_runs: int = 5,
    tolerance: ConsistencyTolerance | None = None,
) -> dict[str, Any]:
    """run_fn(같은 입력으로 회의 1회를 실행해 v2 문서를 반환)을 n_runs번 돌려 일관성을 측정한다.

    run_fn에 실제 run_meeting 부분함수를 주면 실제 모델 편차를, stub을 주면 파이프라인
    결정론(baseline)을 측정한다 — 하네스는 회의 실행 방식에 의존하지 않는다(DI).
    """
    if n_runs < 1:
        raise ValueError("n_runs는 1 이상이어야 합니다.")
    documents = [run_fn() for _ in range(n_runs)]
    return summarize_consistency(documents, tolerance)
