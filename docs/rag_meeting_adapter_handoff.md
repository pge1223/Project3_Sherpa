# 경이님 전달용 — RAG 회의 연동 출력 샘플

요청하신 RAG 어댑터 출력 샘플입니다.

아래 값은 실제 프로젝트/Chroma 데이터가 아니라, 대표 `RoleSearchResponse`와
`LinkedEvaluation` 객체를 현재 로컬의 어댑터 함수에 넣어 실행한 결과입니다.
실제 프로젝트 데이터를 사용한 E2E 검증은 backend 연동 후 추가로 진행하겠습니다.

## 1. `build_meeting_retrieved_evidence()` 출력

```json
[
  {
    "chunk_id": "CHUNK-014",
    "document_id": "DOC-001",
    "persona_id": "business_strategy",
    "role_id": "business_strategy",
    "document_name": "사업계획서.pdf",
    "section": "시장 분석",
    "page": 6,
    "location_number": 6,
    "location_type": "page",
    "text": "초기 목표 고객은 재고관리 전담 인력이 없는 소규모 오프라인 매장이다.",
    "semantic_score": 0.82,
    "role_score": 0.91,
    "final_score": 0.86,
    "score": 0.86
  }
]
```

## 2. `to_linked_evidence_refs()` 출력

```json
[
  {
    "document_id": "DOC-001",
    "chunk_id": "CHUNK-014",
    "quote": "초기 목표 고객은 재고관리 전담 인력이 없는 소규모 오프라인 매장이다.",
    "document_name": "사업계획서.pdf",
    "section": "시장 분석",
    "page": 6,
    "semantic_score": 0.82,
    "role_score": 0.91,
    "final_score": 0.86
  }
]
```

## 3. RAG-006 연동 계획

RAG-006은 합의한 대로 평가 점수 및 RAG-005 충분도 판정에 사용하지 않고,
비교·개선 방향을 위한 참고자료로만 취급하겠습니다.

backend에서는 먼저 검색 호출과 plain data 변환까지 준비하겠습니다.

```python
response = similar_case_service.search(request)
similar_success_cases = response.model_dump()
```

`similar_success_cases`의 `run_meeting` 입출력 및 최종 v2 문서 연결은
`review_output` v2.1.0 계약 확정 후 진행하겠습니다.