"""
Evaluation Dataset Loader
============================
JSON 파일을 EvaluationDataset으로 로드하고 검증한다. 파일 읽기 외에는 상태가 없다.
"""

from __future__ import annotations

import json
from pathlib import Path

from ai.rag.evaluation.schemas import EvaluationDataset


def load_dataset(path: str | Path) -> EvaluationDataset:
    """평가셋 JSON 파일을 읽어 검증된 EvaluationDataset을 반환한다.

    지원하지 않는 domain/persona_id/role_id 조합, 빈 query, 빈 relevant_chunk_ids,
    중복 case_id 등은 EvaluationDataset/EvaluationCase의 pydantic validator가 막는다
    (ValidationError 발생).
    """
    file_path = Path(path)
    raw_text = file_path.read_text(encoding="utf-8")
    raw = json.loads(raw_text)
    return EvaluationDataset.model_validate(raw)
