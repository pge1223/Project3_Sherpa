from ai.rag.evaluation.rag_quality.multi_document_quality import evaluate_multi_document_cases


def _case(project: str, index: int, *, supported: bool = True) -> dict:
    chunk = f"{project}-chunk-{index}"
    return {
        "case_id": f"{project}-{index}",
        "project_id": project,
        "gold_relevant_chunk_ids": [chunk],
        "retrieved_chunk_ids": [chunk],
        "selected_chunk_ids": [chunk],
        "claims": [
            {
                "claim_type": "document_fact",
                "expected_claim_type": "document_fact",
                "supported": supported,
            }
        ],
        "issue_match": True,
        "planner_fallback": False,
        "human_verified": True,
    }


def test_quality_gate_passes_only_with_three_projects_and_fifteen_verified_cases():
    cases = [_case(project, index) for project in ("P1", "P2", "P3") for index in range(5)]
    report = evaluate_multi_document_cases(cases)
    assert report["passed"] is True
    assert report["metrics"]["project_count"] == 3
    assert report["metrics"]["verified_case_count"] == 15
    assert report["metrics"]["citation_precision"] == 1.0


def test_quality_gate_excludes_unverified_and_reports_stage_specific_failures():
    cases = [_case("P1", index, supported=False) for index in range(5)]
    cases.append({**_case("P2", 1), "human_verified": False})
    report = evaluate_multi_document_cases(cases)
    assert report["passed"] is False
    assert report["excluded_unverified_case_count"] == 1
    assert "project_count" in report["failure_reasons"]
    assert "citation_precision" in report["failure_reasons"]
    assert "unsupported_document_fact_rate" in report["failure_reasons"]

