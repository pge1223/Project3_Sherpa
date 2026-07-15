"""
Unit Tests for ai.rag.evidence_linking.linker
"""

from ai.rag.evidence_linking.config import EvidenceLinkingConfig
from ai.rag.evidence_linking.linker import build_linked_evaluation, resolve_score
from ai.rag.evidence_linking.metadata import (
    extract_content_kind,
    extract_document_title,
    extract_page_number,
    extract_section_title,
)
from ai.rag.retrieval.schemas import SearchResult
from ai.rag.role_retrieval.schemas import RoleSearchResult

_OPINION = "예산 산정 기준과 세부 사용 계획이 부족합니다."


def _search_result(record_id, document_id, chunk_id, content, score, metadata=None) -> SearchResult:
    return SearchResult(
        record_id=record_id,
        chunk_id=chunk_id,
        document_id=document_id,
        content=content,
        distance=None if score is None else 1.0 - score,
        score=score,
        metadata=metadata or {},
    )


def _role_result(chunk_id, document_id, content, final_score, semantic_score=0.5, role_score=0.2, metadata=None) -> RoleSearchResult:
    return RoleSearchResult(
        record_id=chunk_id,
        chunk_id=chunk_id,
        document_id=document_id,
        content=content,
        distance=None,
        semantic_score=semantic_score,
        role_score=role_score,
        final_score=final_score,
        role_id="finance",
        metadata=metadata or {},
    )


class TestResolveScore:
    def test_prefers_final_score(self):
        result = _role_result("c1", "d1", "내용", final_score=0.8, semantic_score=0.5)
        assert resolve_score(result) == 0.8

    def test_falls_back_to_semantic_score_when_final_score_missing(self):
        result = _search_result("r1", "d1", "c1", "내용", score=0.6)
        assert resolve_score(result) == 0.6

    def test_returns_zero_when_all_scores_none(self):
        result = _search_result("r1", "d1", "c1", "내용", score=None)
        assert resolve_score(result) == 0.0


class TestBuildLinkedEvaluation:
    def test_high_score_result_selected(self):
        results = [
            _search_result("r1", "d1", "c1", "총사업비는 5,000만 원으로 산정하였다.", score=0.8,
                            metadata={"document_title": "사업계획서.pdf", "section_title": "사업비 구성"}),
        ]
        linked = build_linked_evaluation(_OPINION, results, EvidenceLinkingConfig())
        assert linked.has_evidence is True
        assert linked.evidence[0].document_id == "d1"
        assert linked.evidence[0].document_title == "사업계획서.pdf"

    def test_final_score_used_over_semantic_when_both_present(self):
        results = [_role_result("c1", "d1", "예산 세부 계획 설명", final_score=0.9, semantic_score=0.2)]
        linked = build_linked_evaluation(_OPINION, results, EvidenceLinkingConfig())
        assert linked.evidence[0].final_score == 0.9
        assert linked.evidence[0].semantic_score == 0.2

    def test_semantic_score_fallback_when_no_final_score(self):
        results = [_search_result("r1", "d1", "c1", "예산 세부 계획 설명", score=0.5)]
        linked = build_linked_evaluation(_OPINION, results, EvidenceLinkingConfig())
        assert linked.evidence[0].final_score is None
        assert linked.evidence[0].semantic_score == 0.5

    def test_none_score_treated_as_below_threshold(self):
        results = [_search_result("r1", "d1", "c1", "예산 세부 계획 설명", score=None)]
        linked = build_linked_evaluation(_OPINION, results, EvidenceLinkingConfig())
        assert linked.has_evidence is False

    def test_below_min_score_excluded(self):
        results = [_search_result("r1", "d1", "c1", "예산 세부 계획 설명", score=0.1)]
        linked = build_linked_evaluation(_OPINION, results, EvidenceLinkingConfig(min_evidence_score=0.3))
        assert linked.has_evidence is False
        assert linked.evidence == []

    def test_empty_search_results_gives_no_evidence(self):
        linked = build_linked_evaluation(_OPINION, [], EvidenceLinkingConfig())
        assert linked.has_evidence is False
        assert linked.evidence == []

    def test_duplicate_chunk_id_deduplicated(self):
        results = [
            _search_result("r1", "d1", "c1", "예산 세부 계획 설명 낮은 점수", score=0.4),
            _search_result("r2", "d1", "c1", "예산 세부 계획 설명 높은 점수", score=0.9),
        ]
        linked = build_linked_evaluation(_OPINION, results, EvidenceLinkingConfig())
        assert len(linked.evidence) == 1
        assert "높은 점수" in linked.evidence[0].quote

    def test_max_evidence_limits_result_count(self):
        results = [
            _search_result(f"r{i}", "d1", f"c{i}", "예산 세부 계획 설명", score=0.9 - i * 0.01)
            for i in range(10)
        ]
        linked = build_linked_evaluation(_OPINION, results, EvidenceLinkingConfig(), max_evidence=2)
        assert len(linked.evidence) == 2

    def test_missing_document_id_excluded(self):
        results = [_search_result("r1", "", "c1", "예산 세부 계획 설명", score=0.9)]
        linked = build_linked_evaluation(_OPINION, results, EvidenceLinkingConfig())
        assert linked.has_evidence is False

    def test_missing_chunk_id_excluded(self):
        results = [_search_result("r1", "d1", "", "예산 세부 계획 설명", score=0.9)]
        linked = build_linked_evaluation(_OPINION, results, EvidenceLinkingConfig())
        assert linked.has_evidence is False

    def test_empty_content_excluded(self):
        results = [_search_result("r1", "d1", "c1", "", score=0.9)]
        linked = build_linked_evaluation(_OPINION, results, EvidenceLinkingConfig())
        assert linked.has_evidence is False

    def test_role_id_and_role_name_passed_through(self):
        results = [_search_result("r1", "d1", "c1", "예산 세부 계획 설명", score=0.9)]
        linked = build_linked_evaluation(_OPINION, results, EvidenceLinkingConfig(), role_id="finance", role_name="재무 심사위원")
        assert linked.role_id == "finance"
        assert linked.role_name == "재무 심사위원"

    def test_no_relevant_evidence_at_all_returns_false(self):
        results = [_search_result("r1", "d1", "c1", "완전히 무관한 내용", score=0.1)]
        linked = build_linked_evaluation(_OPINION, results, EvidenceLinkingConfig(min_evidence_score=0.3))
        assert linked.has_evidence is False
        assert linked.evidence == []


class TestRelevanceFilteringInCandidateSelection:
    """RAG-004 추가 검증: 검색 점수가 높아도 평가 의견과 무관한 청크는 근거 후보에서 제외되어야 한다."""

    _SCHEDULE_OPINION = "사업 추진 일정과 실행 계획이 부족합니다."

    def test_high_score_irrelevant_chunk_excluded_low_score_relevant_chunk_selected(self):
        market_chunk = _search_result(
            "r1", "d1", "c1",
            "목표 고객과 SNS 홍보 채널을 분석한다.",
            score=0.95,
            metadata={"section_title": "시장 분석 및 홍보 전략"},
        )
        schedule_chunk = _search_result(
            "r2", "d1", "c2",
            "1단계 기획, 2단계 개발, 3단계 실증 일정으로 진행한다.",
            score=0.75,
            metadata={"section_title": "사업 추진 일정"},
        )
        linked = build_linked_evaluation(
            self._SCHEDULE_OPINION, [market_chunk, schedule_chunk], EvidenceLinkingConfig()
        )
        assert linked.has_evidence is True
        assert len(linked.evidence) == 1
        assert linked.evidence[0].chunk_id == "c2"
        assert all(e.chunk_id != "c1" for e in linked.evidence)

    def test_no_relevant_candidate_returns_no_evidence(self):
        results = [
            _search_result("r1", "d1", "c1", "목표 고객과 SNS 홍보 채널을 분석한다.", score=0.9,
                            metadata={"section_title": "시장 분석"}),
            _search_result("r2", "d1", "c2", "예산은 항목별로 구성되어 있다.", score=0.85,
                            metadata={"section_title": "예산 구성"}),
            _search_result("r3", "d1", "c3", "접수 기간과 제출 서류 안내입니다.", score=0.8,
                            metadata={"section_title": "접수 안내"}),
        ]
        linked = build_linked_evaluation(self._SCHEDULE_OPINION, results, EvidenceLinkingConfig())
        assert linked.has_evidence is False
        assert linked.evidence == []

    def test_section_title_relevance_accepted_even_with_sparse_content_overlap(self):
        results = [
            _search_result(
                "r1", "d1", "c1",
                "각 단계는 순차적으로 진행되며 세부 담당자는 별첨에 정리한다.",
                score=0.6,
                metadata={"section_title": "사업 추진 일정"},
            ),
        ]
        linked = build_linked_evaluation(self._SCHEDULE_OPINION, results, EvidenceLinkingConfig())
        assert linked.has_evidence is True
        assert linked.evidence[0].chunk_id == "c1"

    def test_relevance_prioritized_over_higher_search_score(self):
        results = [
            _search_result("r1", "d1", "c1", "목표 고객과 SNS 홍보 채널을 분석한다.", score=0.95,
                            metadata={"section_title": "시장 분석 및 홍보 전략"}),
            _search_result("r2", "d1", "c2", "1단계 기획, 2단계 개발, 3단계 실증 일정으로 진행한다.", score=0.5,
                            metadata={"section_title": "사업 추진 일정"}),
        ]
        linked = build_linked_evaluation(self._SCHEDULE_OPINION, results, EvidenceLinkingConfig())
        assert linked.has_evidence is True
        assert [e.chunk_id for e in linked.evidence] == ["c2"]

    def test_role_keywords_rescue_relevant_chunk_without_direct_opinion_overlap(self):
        results = [
            _role_result(
                "c1", "d1",
                "고객 응대 방법에 대한 일반 설명이다. 예산 및 자금조달, 재무 위험에 대한 설명이다.",
                final_score=0.9,
            ),
        ]
        linked = build_linked_evaluation(
            "이 사업의 전반적인 완성도를 평가해주세요.",
            results,
            EvidenceLinkingConfig(),
            role_keywords=["예산", "자금조달"],
        )
        assert linked.has_evidence is True

    def test_require_text_relevance_false_disables_filter(self):
        results = [
            _search_result("r1", "d1", "c1", "목표 고객과 SNS 홍보 채널을 분석한다.", score=0.95,
                            metadata={"section_title": "시장 분석 및 홍보 전략"}),
        ]
        linked = build_linked_evaluation(
            self._SCHEDULE_OPINION, results, EvidenceLinkingConfig(require_text_relevance=False)
        )
        assert linked.has_evidence is True


class TestMetadataExtraction:
    def test_document_title_extracted(self):
        assert extract_document_title({"document_title": "사업계획서.pdf"}) == "사업계획서.pdf"

    def test_section_title_extracted(self):
        assert extract_section_title({"section_title": "사업비 구성"}) == "사업비 구성"

    def test_content_kind_extracted(self):
        assert extract_content_kind({"content_kind": "table"}) == "table"

    def test_page_number_extracted_directly(self):
        assert extract_page_number({"page_number": 7}) == 7

    def test_page_fallback(self):
        assert extract_page_number({"page": 4}) == 4

    def test_location_number_fallback(self):
        assert extract_page_number({"location_number": 7}) == 7

    def test_page_index_fallback_converted_to_1_based(self):
        assert extract_page_number({"page_index": 0}) == 1
        assert extract_page_number({"page_index": 6}) == 7

    def test_none_metadata_returns_none_for_all_fields(self):
        assert extract_document_title(None) is None
        assert extract_section_title(None) is None
        assert extract_content_kind(None) is None
        assert extract_page_number(None) is None

    def test_empty_metadata_returns_none_for_all_fields(self):
        assert extract_document_title({}) is None
        assert extract_section_title({}) is None
        assert extract_content_kind({}) is None
        assert extract_page_number({}) is None

    def test_missing_fields_do_not_raise(self):
        metadata = {"document_title": "사업계획서.pdf"}
        assert extract_section_title(metadata) is None
        assert extract_page_number(metadata) is None

    def test_field_priority_page_number_over_location_number(self):
        assert extract_page_number({"page_number": 3, "location_number": 9}) == 3
