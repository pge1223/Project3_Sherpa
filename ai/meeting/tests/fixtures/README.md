<!-- 작성자: 경이 / 목적: M1 Mock 픽스처 설명·출처·승격 계획 / 참조: contracts/schemas/review_output.schema.json, contracts/meeting_rules.json -->

# ai/meeting 테스트 픽스처 (M1 Mock)

경이 담당(LangGraph·점수 엔진) 모듈을 **실제 RAG/LLM 없이 단독 개발·테스트**하기 위한 Mock 데이터다.
병렬개발 원칙상 경이 본인 영역(`ai/meeting/`)에 먼저 두고, 팀 협의 후 공용 `contracts/mocks/`로 승격한다.

## 파일

| 파일 | 성격 | 근거 계약 | 연관 요구사항 |
|---|---|---|---|
| `rag_response.json` | 경이가 **입력으로 소비** (Mock Retriever 결과) | `docs/claude_context.md#8.1` (용준 Retriever JSON, 잠정) | MTG-001 입력 |
| `reviewer_result.json` | 경이가 **생산** (위원별 독립 평가, 2명) | `review_output.schema.json#/$defs/reviewerResult` | MTG-001 |
| `final_meeting_result.json` | 경이가 **생산** (위원장 종합·최종 결과) | `review_output.schema.json` (전체) | MTG-002 |

- 모든 JSON은 맨 위 `_meta` 블록에 작성자·목적·참조를 둔다 (JSON은 주석 불가). 실제 데이터는 `data` 키.
- `data`만 스키마 검증한다. 검증 스크립트 예시는 M8(일관성 테스트)에서 `tests/`로 정식 편입 예정.

## 공통 식별자 (파일 간 일관)

`project_001` / `document_001` / `meeting_001`, 위원 `business_strategy`·`market_analysis`, 근거 `ev_001~003`.

## 승격(→ contracts/mocks/) 전 협의 항목

- **가은**: `contracts/mocks/`는 가은 폴더 → reviewer/final Mock 위치·값 합의 후 승격, 승격 시 `_meta` 제거.
- **용준**: `rag_response.json` 필드 규격을 용준 실제 Retriever 출력으로 교체.
- **윤한**: `final_meeting_result.json`을 DB 저장/리포트 API 참조 예시로 공유.
