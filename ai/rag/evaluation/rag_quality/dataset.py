# 작성자: 용준/Claude(2026-07-22)
# 목적: JSONL 평가셋 로더 + case_id/persona/human_verified 필터 + 사람 검수용 표본 추출.
#       파일 읽기 외에는 상태가 없다(ai/rag/evaluation/dataset.py와 같은 원칙).
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Optional

from ai.rag.evaluation.rag_quality.schemas import RagEvalCase, RagEvalDataset


def load_cases(path: str | Path) -> RagEvalDataset:
    """JSONL 평가셋을 읽어 검증된 RagEvalDataset을 반환한다. 파일 첫 줄이
    {"dataset_name":..., "version":...} 메타 레코드면 헤더로 쓰고, 아니면
    파일명으로 dataset_name/version="unversioned"를 만든다(요청 스키마는 케이스
    레코드 자체에 dataset 메타를 요구하지 않으므로 둘 다 지원)."""
    file_path = Path(path)
    lines = [line for line in file_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        raise ValueError(f"평가셋 파일이 비어 있습니다: {file_path}")

    raw_records = [json.loads(line) for line in lines]

    dataset_name = file_path.stem
    version = "unversioned"
    case_records = raw_records
    first = raw_records[0]
    if "dataset_name" in first and "id" not in first:
        dataset_name = first.get("dataset_name", dataset_name)
        version = first.get("version", version)
        case_records = raw_records[1:]

    cases = [RagEvalCase.model_validate(record) for record in case_records]
    return RagEvalDataset(dataset_name=dataset_name, version=version, cases=cases)


def filter_cases(
    cases: list[RagEvalCase],
    *,
    case_id: Optional[str] = None,
    persona_id: Optional[str] = None,
    human_verified_only: bool = False,
    limit: Optional[int] = None,
) -> list[RagEvalCase]:
    """CLI --case-id/--persona/--human-verified-only/--limit을 순서대로 적용한다."""
    result = cases
    if case_id:
        result = [c for c in result if c.id == case_id]
    if persona_id:
        result = [c for c in result if c.persona_id == persona_id]
    if human_verified_only:
        result = [c for c in result if c.human_verified]
    if limit is not None:
        result = result[:limit]
    return result


def extract_review_sample(cases: list[RagEvalCase], *, fraction: float = 0.15, seed: int = 42) -> list[RagEvalCase]:
    """사람이 검수할 10~20% 표본을 추출한다(요청 7번). human_verified=false 케이스 중에서만
    뽑는다 — 이미 검수된 케이스를 다시 검수 대상으로 내밀 필요가 없다. 결정적 결과를 위해
    seed를 고정한다(기본값 42, 재실행해도 같은 표본)."""
    unverified = [c for c in cases if not c.human_verified]
    if not unverified:
        return []
    n = max(1, round(len(unverified) * fraction))
    rng = random.Random(seed)
    return rng.sample(unverified, min(n, len(unverified)))
