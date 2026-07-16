"""
Unit Tests for ai.rag.evaluation.schemas / dataset
(실제 KURE, Chroma, OpenAI API 없음 — 순수 pydantic validation)
"""

import json

import pytest
from pydantic import ValidationError

from ai.rag.evaluation.dataset import load_dataset
from ai.rag.evaluation.schemas import EvaluationCase, EvaluationDataset


def _valid_case_kwargs(**overrides) -> dict:
    base = dict(
        case_id="competition-001",
        project_id="p1",
        domain="competition",
        persona_id="business_strategy",
        role_id="finance",
        criterion_id="contribution",
        query="사업성과 시장 기여도",
        relevant_chunk_ids=["c1", "c2"],
    )
    base.update(overrides)
    return base


class TestEvaluationCaseValidation:
    def test_valid_case_constructs(self):
        case = EvaluationCase(**_valid_case_kwargs())
        assert case.role_id == "finance"
        assert case.relevant_chunk_ids == ["c1", "c2"]

    def test_blank_case_id_rejected(self):
        with pytest.raises(ValidationError):
            EvaluationCase(**_valid_case_kwargs(case_id=""))

    def test_blank_query_rejected(self):
        with pytest.raises(ValidationError):
            EvaluationCase(**_valid_case_kwargs(query="  "))

    def test_empty_relevant_chunk_ids_rejected(self):
        with pytest.raises(ValidationError):
            EvaluationCase(**_valid_case_kwargs(relevant_chunk_ids=[]))

    def test_duplicate_relevant_chunk_ids_rejected(self):
        with pytest.raises(ValidationError):
            EvaluationCase(**_valid_case_kwargs(relevant_chunk_ids=["c1", "c1"]))

    def test_unsupported_domain_rejected(self):
        with pytest.raises(ValidationError):
            EvaluationCase(**_valid_case_kwargs(domain="government_support"))

    def test_role_id_not_matching_mapping_rejected(self):
        # business_strategy -> finance가 정답인데 다른 role_id를 넣으면 막혀야 한다
        with pytest.raises(ValidationError):
            EvaluationCase(**_valid_case_kwargs(role_id="technology"))

    def test_unmapped_persona_id_rejected(self):
        with pytest.raises(ValidationError):
            EvaluationCase(**_valid_case_kwargs(persona_id="nonexistent_persona", role_id="finance"))

    def test_optional_fields_default_to_none(self):
        case = EvaluationCase(**_valid_case_kwargs(criterion_id=None))
        assert case.expected_sufficiency is None
        assert case.notes is None


class TestEvaluationDatasetValidation:
    def test_valid_dataset_constructs(self):
        dataset = EvaluationDataset(
            dataset_name="competition_retrieval_v1",
            version="1.0.0",
            cases=[_valid_case_kwargs()],
        )
        assert len(dataset.cases) == 1

    def test_duplicate_case_id_rejected(self):
        with pytest.raises(ValidationError):
            EvaluationDataset(
                dataset_name="competition_retrieval_v1",
                version="1.0.0",
                cases=[_valid_case_kwargs(), _valid_case_kwargs()],
            )

    def test_empty_cases_rejected(self):
        with pytest.raises(ValidationError):
            EvaluationDataset(dataset_name="ds", version="1.0.0", cases=[])

    def test_blank_dataset_name_rejected(self):
        with pytest.raises(ValidationError):
            EvaluationDataset(dataset_name="", version="1.0.0", cases=[_valid_case_kwargs()])


class TestLoadDataset:
    def test_load_valid_dataset_from_file(self, tmp_path):
        payload = {
            "dataset_name": "competition_retrieval_v1",
            "version": "1.0.0",
            "cases": [_valid_case_kwargs()],
        }
        dataset_path = tmp_path / "dataset.json"
        dataset_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        dataset = load_dataset(dataset_path)
        assert dataset.dataset_name == "competition_retrieval_v1"
        assert dataset.cases[0].case_id == "competition-001"

    def test_load_invalid_dataset_raises(self, tmp_path):
        payload = {
            "dataset_name": "competition_retrieval_v1",
            "version": "1.0.0",
            "cases": [_valid_case_kwargs(relevant_chunk_ids=[])],
        }
        dataset_path = tmp_path / "dataset.json"
        dataset_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        with pytest.raises(ValidationError):
            load_dataset(dataset_path)

    def test_example_template_is_valid_and_marked_as_sample(self):
        example_path = (
            __import__("pathlib").Path(__file__).resolve().parents[1]
            / "evaluation" / "examples" / "retrieval_golden.example.json"
        )
        raw = json.loads(example_path.read_text(encoding="utf-8"))
        assert "EXAMPLE" in raw["dataset_name"] or "example" in str(example_path).lower()
        dataset = load_dataset(example_path)
        assert len(dataset.cases) >= 1
