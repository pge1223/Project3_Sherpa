# Meeting Evidence Orchestration — RAG-003·004·005 → 회의 연동

## 1. 목적

`ai/meeting/graph`(경이)는 이미 `run_meeting(evidence_context=..., evidence_callback=...)`
계약을 완성하고 테스트까지 끝낸 상태다(`ai/meeting/graph/run.py`,
`ai/meeting/tests/test_evidence_integration.py`). 이 모듈은 그 계약이 요구하는
plain data/callback을 RAG-003(`RoleAwareRetrievalService`)·RAG-004
(`EvidenceLinkingService`)·RAG-005(`EvidenceSufficiencyService`)를 조립해 만든다.

`ai/meeting/graph`는 이 모듈을 몰라도 되고(callback은 그냥 `Callable`), 이 모듈도
`ai.meeting`을 import하지 않는다 — 회의 ↔ RAG 분리는 그대로 유지된다
(`ai/rag/tests/test_meeting_evidence_service.py::TestScopeBoundary`가 두 방향 모두 확인한다).

## 2. backend가 호출할 코드 (analyze_project() 연동 예시)

`backend/app/api/routes/meetings.py`는 이번 작업에서 수정하지 않았다 — 아래는
윤한님이 연결하실 때 참고할 실제 호출 예시다.

```python
from ai.rag.evidence_linking.service import EvidenceLinkingService
from ai.rag.evidence_sufficiency.service import EvidenceSufficiencyService
from ai.rag.orchestration import MeetingEvidenceOrchestrationService
from ai.rag.role_retrieval.service import RoleAwareRetrievalService

# 앱 시작 시 1회 초기화 (documents.py의 기존 RAGIndexingService 인스턴스를 재사용 —
# KUREEmbedder를 두 번 로딩하지 않기 위해 RAG-006과 동일한 패턴).
from app.api.routes.documents import _get_indexing_service

_role_retrieval_service = RoleAwareRetrievalService(retrieval_service=_get_indexing_service())
_evidence_linking_service = EvidenceLinkingService()
_evidence_sufficiency_service = EvidenceSufficiencyService()


# analyze_project() 내부, run_meeting() 호출 전:
evidence_service = MeetingEvidenceOrchestrationService(
    role_retrieval_service=_role_retrieval_service,
    evidence_linking_service=_evidence_linking_service,
    evidence_sufficiency_service=_evidence_sufficiency_service,
    top_k=5,
)

evidence_context = evidence_service.prepare_meeting_evidence(
    project_id=project_id,
    domain=domain,             # rubric_mapping["meta"]["domain"]과 같은 값
    rubric_mapping=mapping,    # _load_rubric_mapping(domain)이 이미 로드한 그 dict
    trace_id=meeting_id,
)
evidence_callback = evidence_service.create_evidence_callback(trace_id=meeting_id)

document = await run_in_threadpool(
    run_meeting,
    meeting_id=meeting_id,
    project_id=project_id,
    document_id=target_doc["_id"],
    title=project.get("title") or submission["document_name"],
    rubric_mapping=mapping,
    submission=submission,
    retrieved_evidence=[],       # evidence_context를 쓰면 flat retrieved_evidence는 비워도 된다
    llm_call=llm_call,
    evidence_context=evidence_context,
    evidence_callback=evidence_callback,
    similar_success_cases=similar_success_cases,
)
```

**주의**: `MeetingEvidenceOrchestrationService` 인스턴스는 **회의 1회(요청 1건)마다 새로
만들어야 한다.** `create_evidence_callback()`이 반환하는 콜백은 직전
`prepare_meeting_evidence()` 호출이 채운 검색 결과 캐시를 참조하므로, 인스턴스를
여러 요청에 재사용하면 다른 회의의 캐시가 섞인다. `RoleAwareRetrievalService`/
`EvidenceLinkingService`/`EvidenceSufficiencyService`(생성자 주입 대상)는 상태가 없어
앱 시작 시 1회만 만들어 재사용해도 된다.

## 3. persona_id → RAG-003 role_id 매핑

`role_mapping.py`가 domain별 매핑을 관리한다. 서비스 코드 어디에도 하드코딩하지 않는다.

```python
role_id = resolve_role_id(domain="competition", persona_id="business_strategy")  # -> "finance"
```

**competition** 도메인(`ai/meeting/personas/rubric_mapping_competition.json`)은 팀이
확정한 매핑을 쓴다:

| persona_id | role_id | 의미 |
|---|---|---|
| `creativity_originality` | `marketing` | 차별성, 사용자 가치, 경쟁 대비 독창성 |
| `technical_feasibility` | `technology` | 기술 구성, 구현 가능성, 보안·운영 |
| `business_strategy` | `finance` | 수익 모델, 비용, 예산, 사업 리스크 |
| `presentation_completeness` | `planning` | 문서 구조, 논리 연결, 일정, 지표, 완성도 |

**government_support 등 다른 도메인은 아직 매핑이 없다.** `rubric_mapping_government_support.json`의
committee(`policy_fit`/`business_strategy`/`technical_feasibility`/`budget_execution`)는
competition과 달라(`policy_fit`/`budget_execution`은 대응하는 role_id가 불명확), 팀 확인
없이 임의로 추가하지 않았다. `government_support` 도메인으로 `prepare_meeting_evidence()`를
호출하면(매핑 없는 persona 발생 시) `PersonaRoleMappingError`가 발생한다 — 이 도메인을
연동하려면 먼저 이 파일에 매핑을 확정해야 한다.

기본 정책은 **strict**다 — 매핑이 없으면 `role_id=None`(semantic-only)으로 조용히
넘어가지 않고 `PersonaRoleMappingError`를 던진다. 완화하려면 명시적으로:

```python
from ai.rag.orchestration import RoleMappingConfig

service = MeetingEvidenceOrchestrationService(
    ...,
    role_mapping_config=RoleMappingConfig(allow_semantic_fallback=True),  # 기본값 False
)
```

fallback이 활성화된 경우에도 매핑 누락마다 `[PERSONA_ROLE_MAPPING_FALLBACK]` warning
로그가 남는다.

criterion 단위 override(같은 persona가 성격이 다른 criterion을 맡을 때)도 지원하지만,
현재 실제로 필요한 override 데이터가 없어 비워뒀다 — `role_mapping.py`의
`_CRITERION_OVERRIDES`에 `{domain: {persona_id: {criterion_id: role_id}}}` 형태로
추가하면 `resolve_role_id(domain=..., persona_id=..., criterion_id=...)`가 자동으로
domain+persona+criterion 매핑을 domain+persona 기본 매핑보다 우선 적용한다.

## 4. 실패 시 정책 — fail-closed

RAG-003 검색, RAG-004 근거 연결, RAG-005 판정 중 어디서든 예외가 발생하면 점수를
허용하는 방향(fail-open)으로 넘어가지 않는다. 항상 다음과 같이 보수적으로 처리된다
(`PersonaRoleMappingError`는 설정 오류라 예외이며, 이건 그대로 올라간다 — 3번 참고):

```json
{
  "linked_evidence_refs": [],
  "sufficiency": {
    "status": "insufficient",
    "allow_numeric_score": false,
    "allow_definitive_judgment": false,
    "reason_codes": []
  }
}
```

## 5. 실제 실행 결과 샘플

손으로 작성한 예시가 아니라, `prepare_meeting_evidence()`/`create_evidence_callback()`을
FakeRetrievalService(mock 하위 검색)로 실제 실행한 결과다(전문은
`docs/rag_orchestration_samples.json` 참고). 이 예시는 근거 1건만 관련성 있게
연결되어 RAG-005 최종 판정이 `partial`(근거 부족)로 내려가 `allow_numeric_score=false`가
되는 실제 게이팅 사례다.

`prepare_meeting_evidence()` 출력(`evidence_context` 1건):

```json
{
  "persona_id": "business_strategy",
  "criterion_id": "contribution",
  "retrieved_evidence": [
    {
      "chunk_id": "CHUNK-021", "document_id": "DOC-001",
      "persona_id": "business_strategy", "role_id": "finance",
      "document_name": "사업계획서.pdf", "section": "수익 모델", "page": 9,
      "text": "재고 데이터를 활용한 수익 모델은 월 구독료 기반으로 설계되었다.",
      "semantic_score": 0.71, "role_score": 0.85, "final_score": 0.745, "score": 0.745
    },
    {
      "chunk_id": "CHUNK-014", "document_id": "DOC-001",
      "persona_id": "business_strategy", "role_id": "finance",
      "document_name": "사업계획서.pdf", "section": "시장 분석", "page": 6,
      "text": "초기 목표 고객은 재고관리 전담 인력이 없는 소규모 오프라인 매장이다. 경쟁 서비스 대비 초기 도입 비용이 낮아 시장 진입 장벽이 낮다.",
      "semantic_score": 0.86, "role_score": 0.15, "final_score": 0.6825, "score": 0.6825
    }
  ],
  "sufficiency": {
    "status": "sufficient",
    "prompt_guard": "검색된 문서 근거 범위 안에서만 평가하세요. ...",
    "allow_numeric_score": true,
    "allow_definitive_judgment": true
  }
}
```

`create_evidence_callback()` 출력(위원 의견 생성 후, 실제로는 1건만 관련 근거로 채택되어 최종 판정이 partial로 내려간 경우):

```json
{
  "linked_evidence_refs": [
    {
      "document_id": "DOC-001", "chunk_id": "CHUNK-014",
      "quote": "초기 목표 고객은 재고관리 전담 인력이 없는 소규모 오프라인 매장이다.",
      "document_name": "사업계획서.pdf", "section": "시장 분석", "page": 6,
      "semantic_score": 0.86, "role_score": 0.15, "final_score": 0.6825
    }
  ],
  "sufficiency": {
    "status": "partial",
    "allow_numeric_score": false,
    "allow_definitive_judgment": false,
    "reason_codes": ["TOO_FEW_EVIDENCE"]
  }
}
```

## 6. 테스트

```
pytest ai/rag/tests/test_role_mapping.py ai/rag/tests/test_meeting_evidence_service.py
```

`ai.meeting.graph`, LangGraph, 실제 Chroma/KURE/LLM을 전혀 쓰지 않는다(RAG-003/004/005는
실제 구현, 맨 밑단 검색만 mock). `ai/rag/tests`, `ai/meeting/tests` 전체 회귀도 함께 통과함을
확인했다(완료 보고 참고).
