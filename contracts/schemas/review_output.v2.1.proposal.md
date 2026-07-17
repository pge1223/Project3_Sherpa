<!-- 작성자: 경이 / 목적: review_output 스키마 v2.0.0 -> v2.1.0 개정 제안(팀 회람용) / 참조: review_output.schema.json(v2.0.0), 용준 RAG-006 SimilarCaseSearchResponse(ai/rag/similar_cases/schemas.py) -->

# 회의 결과 계약 v2.1.0 개정 제안 (DRAFT · 팀 동의 전)

- 제안자: 경이 (contracts/schemas 오너)
- 상태: **승인·적용 완료** — 재인·윤한·용준 동의, 가은 동의(필드 위치 최상위 확인). 세 논의사항(§8)은 모두 권장안(enum / 최상위 / permissive)으로 확정·적용. (본 문서는 변경 이력 기록용으로 유지)
- 변경 성격: **선택 필드 1개 추가 (구조 삭제/변경 없음) → minor bump (v2.0.0 → v2.1.0)**
- 관련 파일
  - 대상 계약: `contracts/schemas/review_output.schema.json`
  - 데이터 출처: 용준 RAG-006 `SimilarCaseSearchResponse` (`ai/rag/similar_cases/schemas.py`)
  - 소비: 재인(영상), 윤한(DB 저장), 가은(리포트 화면)

## 1. 배경 / 문제

용준 RAG-006(유사 성공사례 검색)이 완료됐고, backend가 `SimilarCaseSearchService.search()` 결과를
`model_dump()`한 plain dict를 `run_meeting`에 넘겨 **최종 회의 결과 문서에 참고 자료로 포함**하려고 한다
(decoupling: 그래프는 `ai.rag`를 import하지 않고 입력값을 그대로 전달만 함).

그런데 최종 결과 문서(`review_output.schema.json`)는 **`additionalProperties: false` + `schema_version` const("2.0.0")** 이라,
새 필드를 그냥 얹으면 계약 위반이라 검증에서 걸린다. 따라서 **선택 필드를 정식으로 추가하는 v2.1.0 개정**을 제안한다.

**중요**: RAG-006 결과는 **평가 점수 근거가 아니라 비교·개선용 참고 자료**다(응답에 `reference_only: true`가 박혀 있음).
점수 산정(MTG-003)·근거 충족도(RAG-005)·게이팅에 **영향을 주지 않는다.** 회의 문서 안에서도 평가 결과와 분리된
참고 블록으로만 존재한다.

## 2. 제안 요약

| 구분 | 내용 |
|---|---|
| 신설 | 최상위 **선택** 필드 `similar_success_cases` (`object` 또는 `null`) |
| 변경 | `schema_version`: const `"2.0.0"` → **enum `["2.0.0", "2.1.0"]`** (아래 §5 참고) |
| 유지 | 그 외 모든 필드·구조·enum 그대로. `required` 목록 변경 없음(신설 필드는 선택) |

## 3. 필드 정의 (제안)

```jsonc
// review_output.schema.json 최상위 properties 에 추가
"similar_success_cases": {
  "type": ["object", "null"],
  "description": "RAG-006(유사 성공사례) 검색 결과. 평가 점수 근거가 아니라 비교·개선용 참고 자료다(reference_only). 내부 구조는 ai/rag/similar_cases의 SimilarCaseSearchResponse가 소유하며, 회의 계약은 이 블록을 재검증하지 않는다(pass-through). 회의에서 RAG-006을 돌리지 않으면 null 또는 필드 생략."
}
```

- **의도적으로 내부 구조를 제약하지 않는다(permissive).** RAG-006 스키마가 진화해도 회의 계약이 깨지지 않게,
  이 블록의 내부 검증은 `ai/rag/similar_cases`(용준)에 맡긴다. 회의 계약은 "있으면 object, 없으면 null/생략"만 규정한다.
- `similar_success_cases`는 **`required`에 넣지 않는다** — 기존 문서/목업(필드 없음)도 그대로 유효.

참고: RAG-006 응답의 대략적 형태(`model_dump()` 기준, 재검증은 안 함)
```jsonc
{
  "results": [
    {
      "case_id": "...", "title": "...", "case_type": "award_winner",
      "domain": "competition", "source_name": "...", "source_url": "...",
      "similarity_score": 0.83,
      "matched_criteria": ["창의성"], "similarity_reasons": ["..."],
      "common_points": ["..."], "different_points": ["..."], "current_document_gaps": ["..."],
      "evidence": [{"document_id": "...", "chunk_id": "...", "page": 2, "section": null, "quote": "...", "similarity_score": 0.8}],
      "reference_only": true
    }
  ],
  "total_results": 1, "has_rejected_cases": false, "comparison_mode": "selected_case_gap",
  "query_text": "...", "trace_id": "...", "warnings": [], "reference_only": true
}
```

## 4. JSON 예시 (v2.1.0 문서 일부)

```jsonc
{
  "schema_version": "2.1.0",
  "meeting_id": "MTG-...",
  // ... (rubric / reviewer_results / score_result / chair_summary / top_revisions / evidence / media_script 그대로) ...
  "similar_success_cases": {
    "results": [ /* 위 SimilarCaseResult 목록 */ ],
    "total_results": 1,
    "comparison_mode": "selected_case_gap",
    "reference_only": true
  }
}
```
RAG-006 미실행 회의: `"similar_success_cases": null` 또는 필드 생략(둘 다 유효).

## 5. schema_version 처리 (권장안)

- 선택 필드 추가는 규칙상 **minor bump** → 새로 생성되는 문서는 `schema_version: "2.1.0"`.
- 다만 현재 스키마는 `schema_version`이 **const "2.0.0"** 이라, 그냥 const를 "2.1.0"으로 올리면
  **기존에 저장된 "2.0.0" 문서가 재검증 시 깨진다.**
- **권장: `schema_version`을 `enum ["2.0.0", "2.1.0"]`으로.** 새 파이프라인은 "2.1.0"을 내보내고, 기존 "2.0.0"
  문서(저장분·목업)도 그대로 유효하게 둔다. (규칙상 버전은 올라가되, 하위호환 유지)

## 6. 영향 범위 / 협의 대상

| 담당 | 영향 | 필요 확인 |
|---|---|---|
| **재인** | 영상 파이프라인이 문서를 소비. `media_script`는 그대로 | 추가 필드 무시하면 됨(영향 없음). "2.0.0" 하드코딩 체크 있는지만 확인 |
| **윤한** | DB 저장 문서에 필드 추가, `schema_version` enum화 | 저장/검증 로직에서 `schema_version == "2.0.0"` 하드코딩 있으면 enum 허용으로 |
| **가은** | 리포트 화면. 유사사례 비교 UI에서 이 필드 소비 가능 | "2.0.0" 상수 비교 있으면 조정. UI는 선택 소비 |
| **용준** | RAG-006 결과를 backend에서 `model_dump()`로 넘김 | 필드명 `similar_success_cases` / null 규약 확인 |
| **경이** | `run_meeting` 입력·출력에 필드 연결, 목업/fixture 갱신 | 본 제안 주관 |

## 7. 팀 변경 절차 체크리스트 (docs/04_TEAM_WORKFLOW.md §5)

- [x] 변경 제안 작성 (본 문서)
- [x] JSON 예시 공유 (§4)
- [x] 영향 담당자 확인 (재인·윤한·가은·용준)
- [x] 팀 동의
- [x] `schema_version` enum화 + `similar_success_cases` 필드 추가 (`review_output.schema.json`)
- [x] 코드 반영 (`run_meeting`/`assemble_document` 입력·출력에 `similar_success_cases` pass-through, 신규 문서 `schema_version: "2.1.0"`)
- [~] Mock/fixture: 기존 "2.0.0" 목업은 enum으로 그대로 유효 → 강제 갱신 불필요. 새 문서만 "2.1.0" 발행

## 8. 미해결 질문 (팀 논의)

1. `schema_version`을 enum(권장, 하위호환) vs const "2.1.0"(깔끔하지만 기존 문서 무효) 중 무엇으로?
2. `similar_success_cases`를 최상위(제안)로 둘지, `meta` 하위로 둘지 — 최상위가 소비 편하고 평가와 분리도 명확해 최상위를 권장.
3. 유사사례 내부 구조를 계약에서 permissive(제안)로 둘지, `$defs`로 엄격히 명세할지 — RAG-006 진화 대비 permissive 권장.
