"""
Unit Tests for ai.rag.orchestration.meeting_evidence_service
(RAG-003 RoleAwareRetrievalService/RAG-004 EvidenceLinkingService/RAG-005
EvidenceSufficiencyService는 실제 구현을 그대로 쓰되, 맨 밑단의 검색만
FakeRetrievalService(mock)로 대체한다 — 실제 Chroma/KURE/LLM/LangGraph 없음.
ai.meeting.graph는 import하지 않는다.)
"""

from pathlib import Path

import pytest

from ai.rag.evidence_linking.service import EvidenceLinkingService
from ai.rag.evidence_sufficiency.service import EvidenceSufficiencyService
from ai.rag.orchestration.meeting_evidence_service import MeetingEvidenceOrchestrationService
from ai.rag.orchestration.role_mapping import PersonaRoleMappingError, RoleMappingConfig
from ai.rag.retrieval.schemas import SearchResult
from ai.rag.role_retrieval.service import RoleAwareRetrievalService

REPO_ROOT = Path(__file__).resolve().parents[3]


class FakeRetrievalService:
    """RAGIndexingService.search()와 동일한 시그니처의 mock. project_id별로 미리 등록된
    SearchResult만 반환한다(ai/rag/tests/test_role_retrieval_service.py와 동일 패턴)."""

    def __init__(self, records_by_project: dict[str, list[SearchResult]], raise_for_project: str | None = None):
        self._records_by_project = records_by_project
        self._raise_for_project = raise_for_project
        self.calls: list[dict] = []

    def search(self, query, project_id, document_id=None, top_k=5):
        self.calls.append({"query": query, "project_id": project_id, "top_k": top_k})
        if project_id == self._raise_for_project:
            raise RuntimeError("시뮬레이션된 RAG-003 하위 검색 실패")
        return list(self._records_by_project.get(project_id, []))[:top_k]


def _result(record_id, document_id, content, score, section_title=None) -> SearchResult:
    return SearchResult(
        record_id=record_id,
        chunk_id=record_id,
        document_id=document_id,
        content=content,
        distance=1.0 - score,
        score=score,
        metadata={"section_title": section_title, "document_title": "제출문서.pdf", "content_kind": "body"},
    )


# 실제 근거 충분도 임계값(EvidenceSufficiencyConfig.preferred_evidence_count=2)에 걸리도록
# 한 criterion에는 근거 2건(충분), 다른 criterion에는 0건(불충분)을 준비한다.
_GOOD_RECORDS = [
    _result("r1", "doc-a", "친환경 소재를 활용한 독창적인 디자인 차별화 요소가 있다.", 0.8, "창의성 개요"),
    _result("r2", "doc-a", "경쟁작 대비 사용자 가치가 뚜렷한 독창적 디자인을 제시한다.", 0.75, "차별성 분석"),
]


def _make_service(
    fake: FakeRetrievalService,
    *,
    role_mapping_config: RoleMappingConfig | None = None,
    top_k: int = 5,
) -> MeetingEvidenceOrchestrationService:
    return MeetingEvidenceOrchestrationService(
        role_retrieval_service=RoleAwareRetrievalService(retrieval_service=fake),
        evidence_linking_service=EvidenceLinkingService(),
        evidence_sufficiency_service=EvidenceSufficiencyService(),
        role_mapping_config=role_mapping_config,
        top_k=top_k,
    )


def _rubric_mapping(criteria: list[tuple[str, str, str]]) -> dict:
    """criteria: [(criterion_id, criterion_name, primary_persona_id), ...]로 최소 rubric_mapping을 만든다."""
    return {
        "committee": sorted({persona_id for _, _, persona_id in criteria}),
        "total_max_score": 25 * len(criteria),
        "rubric": [
            {
                "criterion_id": cid,
                "criterion_name": cname,
                "max_score": 25,
                "required": True,
                "primary_persona_id": persona_id,
                "secondary_persona_id": None,
            }
            for cid, cname, persona_id in criteria
        ],
    }


_MAPPING = _rubric_mapping(
    [
        ("creativity_appropriateness", "창의성 및 적정성", "creativity_originality"),
        ("contribution", "기여도", "business_strategy"),
    ]
)


def _government_support_rubric_mapping() -> dict:
    """rubric_mapping_government_support.json과 동일한 구조의 fixture(secondary_persona_id 포함)."""
    return {
        "committee": ["policy_fit", "business_strategy", "technical_feasibility", "budget_execution"],
        "total_max_score": 100,
        "rubric": [
            {
                "criterion_id": "necessity",
                "criterion_name": "사업 필요성",
                "max_score": 20,
                "required": True,
                "primary_persona_id": "business_strategy",
                "secondary_persona_id": None,
            },
            {
                "criterion_id": "feasibility",
                "criterion_name": "사업화 가능성",
                "max_score": 25,
                "required": True,
                "primary_persona_id": "business_strategy",
                "secondary_persona_id": None,
            },
            {
                "criterion_id": "tech_capability",
                "criterion_name": "기술성 및 수행역량",
                "max_score": 25,
                "required": True,
                "primary_persona_id": "technical_feasibility",
                "secondary_persona_id": None,
            },
            {
                "criterion_id": "execution_plan",
                "criterion_name": "추진계획 적정성",
                "max_score": 20,
                "required": True,
                "primary_persona_id": "budget_execution",
                "secondary_persona_id": "technical_feasibility",
            },
            {
                "criterion_id": "policy_alignment",
                "criterion_name": "정책 부합성",
                "max_score": 10,
                "required": True,
                "primary_persona_id": "policy_fit",
                "secondary_persona_id": None,
            },
        ],
    }


_GOVERNMENT_SUPPORT_MAPPING = _government_support_rubric_mapping()


class TestPrepareMeetingEvidenceSearch:
    def test_calls_role_aware_search_per_persona_criterion(self):
        fake = FakeRetrievalService({"p1": _GOOD_RECORDS})
        service = _make_service(fake)
        service.prepare_meeting_evidence(project_id="p1", domain="competition", rubric_mapping=_MAPPING)
        assert len(fake.calls) == 2
        assert {c["project_id"] for c in fake.calls} == {"p1"}

    def test_query_uses_criterion_name(self):
        # RoleAwareRetrievalService가 role_profile.query_instruction을 앞에 붙여 확장하므로
        # (build_expanded_query), 하위 검색에 전달되는 값은 criterion_name을 포함한 확장 질의다.
        fake = FakeRetrievalService({"p1": _GOOD_RECORDS})
        service = _make_service(fake)
        service.prepare_meeting_evidence(project_id="p1", domain="competition", rubric_mapping=_MAPPING)
        queries = [c["query"] for c in fake.calls]
        assert any("창의성 및 적정성" in q for q in queries)
        assert any("기여도" in q for q in queries)

    def test_unmapped_persona_raises_persona_role_mapping_error(self):
        mapping = _rubric_mapping([("x", "알 수 없는 항목", "no_such_persona")])
        fake = FakeRetrievalService({"p1": _GOOD_RECORDS})
        service = _make_service(fake)
        with pytest.raises(PersonaRoleMappingError):
            service.prepare_meeting_evidence(project_id="p1", domain="competition", rubric_mapping=mapping)


class TestPrepareMeetingEvidencePlainData:
    def test_returns_plain_list_of_dicts(self):
        fake = FakeRetrievalService({"p1": _GOOD_RECORDS})
        service = _make_service(fake)
        entries = service.prepare_meeting_evidence(project_id="p1", domain="competition", rubric_mapping=_MAPPING)
        assert isinstance(entries, list)
        for entry in entries:
            assert isinstance(entry, dict)
            assert isinstance(entry["retrieved_evidence"], list)
            for item in entry["retrieved_evidence"]:
                assert isinstance(item, dict)

    def test_persona_and_criterion_ids_preserved(self):
        fake = FakeRetrievalService({"p1": _GOOD_RECORDS})
        service = _make_service(fake)
        entries = service.prepare_meeting_evidence(project_id="p1", domain="competition", rubric_mapping=_MAPPING)
        pairs = {(e["persona_id"], e["criterion_id"]) for e in entries}
        assert pairs == {
            ("creativity_originality", "creativity_appropriateness"),
            ("business_strategy", "contribution"),
        }

    def test_prompt_guard_present_per_entry(self):
        fake = FakeRetrievalService({"p1": _GOOD_RECORDS})
        service = _make_service(fake)
        entries = service.prepare_meeting_evidence(project_id="p1", domain="competition", rubric_mapping=_MAPPING)
        for entry in entries:
            assert entry["sufficiency"]["prompt_guard"]

    def test_sufficient_evidence_allows_numeric_score(self):
        # creativity_appropriateness는 관련성 있는 근거 2건(preferred_evidence_count=2)을 받는다.
        fake = FakeRetrievalService({"p1": _GOOD_RECORDS})
        service = _make_service(fake)
        entries = service.prepare_meeting_evidence(project_id="p1", domain="competition", rubric_mapping=_MAPPING)
        creativity_entry = next(e for e in entries if e["criterion_id"] == "creativity_appropriateness")
        assert creativity_entry["sufficiency"]["allow_numeric_score"] is True

    def test_no_evidence_blocks_numeric_score(self):
        # business_strategy/contribution은 project에 등록된 근거가 없어 insufficient가 되어야 한다.
        fake = FakeRetrievalService({"p1": []})
        service = _make_service(fake)
        entries = service.prepare_meeting_evidence(project_id="p1", domain="competition", rubric_mapping=_MAPPING)
        contribution_entry = next(e for e in entries if e["criterion_id"] == "contribution")
        assert contribution_entry["sufficiency"]["allow_numeric_score"] is False
        assert contribution_entry["sufficiency"]["status"] == "insufficient"


class TestPrepareMeetingEvidenceFailClosed:
    def test_search_failure_yields_fail_closed_entry_not_error(self):
        fake = FakeRetrievalService({"p1": _GOOD_RECORDS}, raise_for_project="p1")
        service = _make_service(fake)
        entries = service.prepare_meeting_evidence(project_id="p1", domain="competition", rubric_mapping=_MAPPING)
        assert len(entries) == 2
        for entry in entries:
            assert entry["retrieved_evidence"] == []
            assert entry["sufficiency"]["allow_numeric_score"] is False
            assert entry["sufficiency"]["status"] == "insufficient"


class TestSearchIsolationAcrossPersonaCriterion:
    def test_results_do_not_leak_between_criteria(self):
        records = {
            "p1": [
                _result("only-creativity", "doc-a", "친환경 소재 독창성 근거", 0.9, "창의성"),
            ]
        }
        fake = FakeRetrievalService(records)
        service = _make_service(fake)
        entries = service.prepare_meeting_evidence(project_id="p1", domain="competition", rubric_mapping=_MAPPING)
        by_criterion = {e["criterion_id"]: e["retrieved_evidence"] for e in entries}
        # 두 criterion 모두 같은 project에서 검색하지만, 캐시는 (persona,criterion)별로 분리 저장된다.
        assert service._search_cache.keys() == {
            ("creativity_originality", "creativity_appropriateness"),
            ("business_strategy", "contribution"),
        }


class TestEvidenceCallback:
    def _review_item(self, criterion_id: str, criterion_name: str) -> dict:
        return {
            "criterion_id": criterion_id,
            "criterion_name": criterion_name,
            "strengths": ["친환경 소재를 활용한 독창적인 디자인"],
            "weaknesses": [],
            "improvement_actions": [],
        }

    def test_callback_calls_rag004_link_evidence(self):
        fake = FakeRetrievalService({"p1": _GOOD_RECORDS})
        service = _make_service(fake)
        service.prepare_meeting_evidence(project_id="p1", domain="competition", rubric_mapping=_MAPPING)
        callback = service.create_evidence_callback()
        result = callback(
            "creativity_originality",
            "creativity_appropriateness",
            self._review_item("creativity_appropriateness", "창의성 및 적정성"),
        )
        assert "linked_evidence_refs" in result
        assert "sufficiency" in result

    def test_callback_returns_linked_refs_shape(self):
        fake = FakeRetrievalService({"p1": _GOOD_RECORDS})
        service = _make_service(fake)
        service.prepare_meeting_evidence(project_id="p1", domain="competition", rubric_mapping=_MAPPING)
        callback = service.create_evidence_callback()
        result = callback(
            "creativity_originality",
            "creativity_appropriateness",
            self._review_item("creativity_appropriateness", "창의성 및 적정성"),
        )
        for ref in result["linked_evidence_refs"]:
            assert set(ref.keys()) >= {"document_id", "chunk_id", "quote"}
            assert "evidence_id" not in ref  # A안: evidence_id는 회의 쪽(EvidencePool)이 발급

    def test_callback_sufficient_allows_numeric_score(self):
        fake = FakeRetrievalService({"p1": _GOOD_RECORDS})
        service = _make_service(fake)
        service.prepare_meeting_evidence(project_id="p1", domain="competition", rubric_mapping=_MAPPING)
        callback = service.create_evidence_callback()
        result = callback(
            "creativity_originality",
            "creativity_appropriateness",
            self._review_item("creativity_appropriateness", "창의성 및 적정성"),
        )
        assert result["sufficiency"]["allow_numeric_score"] is True

    def test_callback_no_cached_search_is_insufficient_and_blocks_score(self):
        fake = FakeRetrievalService({"p1": []})
        service = _make_service(fake)
        service.prepare_meeting_evidence(project_id="p1", domain="competition", rubric_mapping=_MAPPING)
        callback = service.create_evidence_callback()
        result = callback(
            "business_strategy", "contribution", self._review_item("contribution", "기여도")
        )
        assert result["linked_evidence_refs"] == []
        assert result["sufficiency"]["allow_numeric_score"] is False
        assert result["sufficiency"]["status"] == "insufficient"

    def test_only_gated_criterion_blocked_other_unaffected(self):
        fake = FakeRetrievalService({"p1": _GOOD_RECORDS})
        service = _make_service(fake)
        service.prepare_meeting_evidence(project_id="p1", domain="competition", rubric_mapping=_MAPPING)
        callback = service.create_evidence_callback()

        good_result = callback(
            "creativity_originality",
            "creativity_appropriateness",
            self._review_item("creativity_appropriateness", "창의성 및 적정성"),
        )
        # contribution의 검색 캐시는 비어 있으므로(등록되지 않음) 별도로 채워 넣어 "근거 없음" 케이스를 만든다.
        service._search_cache[("business_strategy", "contribution")] = service._search_cache[
            ("creativity_originality", "creativity_appropriateness")
        ].model_copy(update={"results": []})
        blocked_result = callback("business_strategy", "contribution", self._review_item("contribution", "기여도"))

        assert good_result["sufficiency"]["allow_numeric_score"] is True
        assert blocked_result["sufficiency"]["allow_numeric_score"] is False

    def test_callback_failure_is_fail_closed_not_fail_open(self, monkeypatch):
        fake = FakeRetrievalService({"p1": _GOOD_RECORDS})
        service = _make_service(fake)
        service.prepare_meeting_evidence(project_id="p1", domain="competition", rubric_mapping=_MAPPING)

        def _boom(*args, **kwargs):
            raise RuntimeError("시뮬레이션된 RAG-004 실패")

        monkeypatch.setattr(service._evidence_linking_service, "link_evidence", _boom)
        callback = service.create_evidence_callback()
        result = callback(
            "creativity_originality",
            "creativity_appropriateness",
            self._review_item("creativity_appropriateness", "창의성 및 적정성"),
        )
        assert result["linked_evidence_refs"] == []
        assert result["sufficiency"]["allow_numeric_score"] is False
        assert result["sufficiency"]["allow_definitive_judgment"] is False


class TestGovernmentSupportOrchestration:
    def _load_real_rubric_mapping(self) -> dict:
        import json

        path = REPO_ROOT / "ai" / "meeting" / "personas" / "rubric_mapping_government_support.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_real_rubric_mapping_file_completes_without_persona_role_mapping_error(self):
        mapping = self._load_real_rubric_mapping()
        fake = FakeRetrievalService({"p1": _GOOD_RECORDS})
        service = _make_service(fake)
        entries = service.prepare_meeting_evidence(
            project_id="p1", domain="government_support", rubric_mapping=mapping
        )
        assert len(entries) > 0

    def test_fixture_rubric_mapping_completes_without_persona_role_mapping_error(self):
        fake = FakeRetrievalService({"p1": _GOOD_RECORDS})
        service = _make_service(fake)
        entries = service.prepare_meeting_evidence(
            project_id="p1", domain="government_support", rubric_mapping=_GOVERNMENT_SUPPORT_MAPPING
        )
        # rubric 5개 항목 + execution_plan의 secondary_persona_id(technical_feasibility)가
        # 별도 (persona_id, criterion_id) 조합으로 추가되어 총 6건.
        assert len(entries) == 6

    def test_policy_fit_search_uses_policy_role_id(self):
        fake = FakeRetrievalService({"p1": _GOOD_RECORDS})
        service = _make_service(fake)
        service.prepare_meeting_evidence(
            project_id="p1", domain="government_support", rubric_mapping=_GOVERNMENT_SUPPORT_MAPPING
        )
        role_response = service._search_cache[("policy_fit", "policy_alignment")]
        assert role_response.role_id == "policy"

    def test_budget_execution_search_uses_budget_execution_role_id(self):
        fake = FakeRetrievalService({"p1": _GOOD_RECORDS})
        service = _make_service(fake)
        service.prepare_meeting_evidence(
            project_id="p1", domain="government_support", rubric_mapping=_GOVERNMENT_SUPPORT_MAPPING
        )
        role_response = service._search_cache[("budget_execution", "execution_plan")]
        assert role_response.role_id == "budget_execution"

    def test_business_strategy_necessity_uses_planning_role_id(self):
        fake = FakeRetrievalService({"p1": _GOOD_RECORDS})
        service = _make_service(fake)
        service.prepare_meeting_evidence(
            project_id="p1", domain="government_support", rubric_mapping=_GOVERNMENT_SUPPORT_MAPPING
        )
        role_response = service._search_cache[("business_strategy", "necessity")]
        assert role_response.role_id == "planning"

    def test_business_strategy_feasibility_uses_marketing_override_role_id(self):
        fake = FakeRetrievalService({"p1": _GOOD_RECORDS})
        service = _make_service(fake)
        service.prepare_meeting_evidence(
            project_id="p1", domain="government_support", rubric_mapping=_GOVERNMENT_SUPPORT_MAPPING
        )
        role_response = service._search_cache[("business_strategy", "feasibility")]
        assert role_response.role_id == "marketing"

    def test_technical_feasibility_uses_technology_role_id(self):
        fake = FakeRetrievalService({"p1": _GOOD_RECORDS})
        service = _make_service(fake)
        service.prepare_meeting_evidence(
            project_id="p1", domain="government_support", rubric_mapping=_GOVERNMENT_SUPPORT_MAPPING
        )
        role_response = service._search_cache[("technical_feasibility", "tech_capability")]
        assert role_response.role_id == "technology"

    def test_execution_plan_primary_and_secondary_persona_have_independent_cache_keys(self):
        # execution_plan은 primary=budget_execution, secondary=technical_feasibility로
        # iter_persona_criteria()가 두 persona 모두를 분리된 (persona_id, criterion_id)
        # 캐시 키로 검색한다.
        fake = FakeRetrievalService({"p1": _GOOD_RECORDS})
        service = _make_service(fake)
        service.prepare_meeting_evidence(
            project_id="p1", domain="government_support", rubric_mapping=_GOVERNMENT_SUPPORT_MAPPING
        )
        assert ("budget_execution", "execution_plan") in service._search_cache
        assert ("technical_feasibility", "execution_plan") in service._search_cache
        primary = service._search_cache[("budget_execution", "execution_plan")]
        secondary = service._search_cache[("technical_feasibility", "execution_plan")]
        assert primary.role_id == "budget_execution"
        assert secondary.role_id == "technology"

    def test_returns_plain_evidence_context_data_contract(self):
        fake = FakeRetrievalService({"p1": _GOOD_RECORDS})
        service = _make_service(fake)
        entries = service.prepare_meeting_evidence(
            project_id="p1", domain="government_support", rubric_mapping=_GOVERNMENT_SUPPORT_MAPPING
        )
        for entry in entries:
            assert isinstance(entry, dict)
            assert set(entry.keys()) >= {"persona_id", "criterion_id", "retrieved_evidence", "sufficiency"}
            assert isinstance(entry["retrieved_evidence"], list)


class TestScopeBoundary:
    """ai/meeting/graph는 이 오케스트레이션(ai.rag)을 import하지 않아야 한다(decoupling 유지).
    graph 파일 자체는 이번 작업에서 수정하지 않았으므로 read-only로 확인만 한다."""

    def test_graph_modules_do_not_import_ai_rag(self):
        graph_dir = REPO_ROOT / "ai" / "meeting" / "graph"
        offending = []
        for path in graph_dir.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("import ai.rag") or stripped.startswith("from ai.rag"):
                    offending.append(str(path))
        assert offending == []

    def test_orchestration_module_does_not_import_ai_meeting(self):
        orchestration_dir = REPO_ROOT / "ai" / "rag" / "orchestration"
        offending = []
        for path in orchestration_dir.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("import ai.meeting") or stripped.startswith("from ai.meeting"):
                    offending.append(str(path))
        assert offending == []
