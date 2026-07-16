"""
Unit Tests for ai.rag.similar_cases.comparison_service (RAG-006)
======================================================================
외부 LLM API를 호출하지 않는다 — llm_call은 항상 순수 mock 함수로 대체한다.
"""

import json

from ai.rag.similar_cases.comparison_service import CaseAggregate, SupportingChunk, compare_case
from ai.rag.similar_cases.schemas import SimilarCaseSearchRequest, SimilarCaseType


def _request(**overrides) -> SimilarCaseSearchRequest:
    base = dict(
        document_summary="AI를 활용해 공공기관의 사업계획서를 자동 평가하는 서비스입니다.",
        domain="public_service",
        evaluation_criteria=["문제 정의", "기술성"],
    )
    base.update(overrides)
    return SimilarCaseSearchRequest(**base)


def _case_aggregate(**overrides) -> CaseAggregate:
    base = dict(
        case_id="CASE-001",
        title="공공데이터 활용 공모전 수상작",
        case_type=SimilarCaseType.AWARD_WINNER,
        domain="public_service",
        evaluation_criteria=["문제 정의", "기술성", "사업성"],
        supporting_chunks=[
            SupportingChunk(
                document_id="d1", chunk_id="c1",
                content="본 서비스는 공공기관의 사업계획서를 AI로 자동 평가합니다.",
                page=3, section="개요", score=0.82,
            )
        ],
    )
    base.update(overrides)
    return CaseAggregate(**base)


class TestRuleBasedComparison:
    def test_domain_match_produces_reason_and_common_point(self):
        outcome = compare_case(_request(domain="public_service"), _case_aggregate(domain="public_service"))
        assert any("public_service" in r for r in outcome.similarity_reasons)
        assert any("public_service" in c for c in outcome.common_points)

    def test_matched_criteria_produces_reason_and_common_point(self):
        outcome = compare_case(
            _request(evaluation_criteria=["기술성"]),
            _case_aggregate(evaluation_criteria=["기술성", "사업성"]),
        )
        assert any("기술성" in r for r in outcome.similarity_reasons)
        assert any("기술성" in c for c in outcome.common_points)

    def test_case_only_criteria_produce_different_points_and_safe_gap_wording(self):
        outcome = compare_case(
            _request(evaluation_criteria=["문제 정의"]),
            _case_aggregate(evaluation_criteria=["문제 정의", "사업성"]),
        )
        assert any("사업성" in d for d in outcome.different_points)
        gap_texts = " ".join(outcome.current_document_gaps)
        assert "사업성" in gap_texts
        assert "확인하기 어렵습니다" in gap_texts

    def test_gap_wording_never_states_absence_definitively(self):
        outcome = compare_case(
            _request(evaluation_criteria=["문제 정의"]),
            _case_aggregate(evaluation_criteria=["문제 정의", "정량적 성과"]),
        )
        for gap in outcome.current_document_gaps:
            assert "없습니다" not in gap
            assert "확인하기 어렵습니다" in gap

    def test_keyword_overlap_between_summary_and_chunk_produces_reason(self):
        outcome = compare_case(
            _request(document_summary="공공기관 사업계획서를 평가하는 서비스입니다."),
            _case_aggregate(
                evaluation_criteria=[],
                supporting_chunks=[
                    SupportingChunk(document_id="d1", chunk_id="c1", content="본 사업계획서는 공공기관 대상입니다.")
                ],
            ),
        )
        assert len(outcome.similarity_reasons) > 0

    def test_no_overlap_returns_empty_reasons_not_fabricated(self):
        outcome = compare_case(
            _request(document_summary="완전히 무관한 내용의 요약입니다.", domain="agri", evaluation_criteria=["농업 기술"]),
            _case_aggregate(
                domain="finance",
                evaluation_criteria=["재무 건전성"],
                supporting_chunks=[
                    SupportingChunk(document_id="d1", chunk_id="c1", content="전혀 다른 주제의 청크 내용입니다.")
                ],
            ),
        )
        assert outcome.similarity_reasons == []

    def test_high_similarity_score_alone_is_not_used_as_reason(self):
        # supporting_chunks에 score만 높고 실제 겹치는 내용이 없으면 이유가 생기지 않아야 한다.
        outcome = compare_case(
            _request(document_summary="완전히 무관한 내용", domain="agri", evaluation_criteria=["농업 기술"]),
            _case_aggregate(
                domain="finance",
                evaluation_criteria=["재무 건전성"],
                supporting_chunks=[
                    SupportingChunk(document_id="d1", chunk_id="c1", content="전혀 다른 내용", score=0.99)
                ],
            ),
        )
        assert not any("점수" in r or "유사도" in r for r in outcome.similarity_reasons)

    def test_rejected_case_does_not_generate_criteria_or_keyword_gaps(self):
        outcome = compare_case(
            _request(evaluation_criteria=["문제 정의"]),
            _case_aggregate(
                case_type=SimilarCaseType.REJECTED_CASE,
                evaluation_criteria=["문제 정의", "사업성"],
                supporting_chunks=[
                    SupportingChunk(document_id="d1", chunk_id="c1", content="탈락 사례에만 있는 고유 키워드입니다.")
                ],
            ),
        )
        assert outcome.different_points == []
        assert outcome.current_document_gaps == []

    def test_used_llm_false_for_rule_based_path(self):
        outcome = compare_case(_request(), _case_aggregate())
        assert outcome.used_llm is False

    def test_result_bounded_in_length(self):
        many_criteria = [f"criterion-{i}" for i in range(20)]
        outcome = compare_case(
            _request(evaluation_criteria=many_criteria),
            _case_aggregate(evaluation_criteria=many_criteria),
        )
        assert len(outcome.similarity_reasons) <= 4
        assert len(outcome.common_points) <= 4
        assert len(outcome.different_points) <= 3
        assert len(outcome.current_document_gaps) <= 3


class TestLLMComparison:
    def test_valid_llm_json_is_used(self):
        def fake_llm(prompt: str) -> str:
            return json.dumps({
                "similarity_reasons": ["LLM 기반 이유"],
                "common_points": ["LLM 공통점"],
                "different_points": ["LLM 차이점"],
                "current_document_gaps": ["LLM 부족점"],
            })

        outcome = compare_case(_request(), _case_aggregate(), llm_call=fake_llm)
        assert outcome.used_llm is True
        assert outcome.similarity_reasons == ["LLM 기반 이유"]

    def test_malformed_json_falls_back_to_rule_based(self):
        def broken_llm(prompt: str) -> str:
            return "이것은 JSON이 아닙니다."

        outcome = compare_case(_request(), _case_aggregate(), llm_call=broken_llm)
        assert outcome.used_llm is False

    def test_missing_required_key_falls_back(self):
        def incomplete_llm(prompt: str) -> str:
            return json.dumps({"similarity_reasons": ["이유"]})  # 나머지 키 누락

        outcome = compare_case(_request(), _case_aggregate(), llm_call=incomplete_llm)
        assert outcome.used_llm is False

    def test_wrong_type_falls_back(self):
        def wrong_type_llm(prompt: str) -> str:
            return json.dumps({
                "similarity_reasons": "문자열이 아닌 리스트여야 함",
                "common_points": [],
                "different_points": [],
                "current_document_gaps": [],
            })

        outcome = compare_case(_request(), _case_aggregate(), llm_call=wrong_type_llm)
        assert outcome.used_llm is False

    def test_llm_exception_falls_back_without_raising(self):
        def raising_llm(prompt: str) -> str:
            raise RuntimeError("외부 LLM API 연결 실패")

        outcome = compare_case(_request(), _case_aggregate(), llm_call=raising_llm)
        assert outcome.used_llm is False
        assert isinstance(outcome.similarity_reasons, list)

    def test_llm_receives_only_provided_content(self):
        captured_prompt = {}

        def spy_llm(prompt: str) -> str:
            captured_prompt["text"] = prompt
            return json.dumps(
                {"similarity_reasons": [], "common_points": [], "different_points": [], "current_document_gaps": []}
            )

        case = _case_aggregate(
            supporting_chunks=[
                SupportingChunk(document_id="d1", chunk_id="c1", content="이 문장은 프롬프트에 포함되어야 합니다.")
            ]
        )
        compare_case(_request(), case, llm_call=spy_llm)

        assert "이 문장은 프롬프트에 포함되어야 합니다." in captured_prompt["text"]
        assert case.title in captured_prompt["text"]

    def test_markdown_fenced_json_parsed(self):
        def fenced_llm(prompt: str) -> str:
            payload = json.dumps(
                {"similarity_reasons": ["이유"], "common_points": [], "different_points": [], "current_document_gaps": []}
            )
            return f"```json\n{payload}\n```"

        outcome = compare_case(_request(), _case_aggregate(), llm_call=fenced_llm)
        assert outcome.used_llm is True
        assert outcome.similarity_reasons == ["이유"]


class TestComparisonNeverRaises:
    def test_compare_case_does_not_raise_on_empty_supporting_chunks(self):
        outcome = compare_case(_request(), _case_aggregate(supporting_chunks=[]))
        assert isinstance(outcome.similarity_reasons, list)
