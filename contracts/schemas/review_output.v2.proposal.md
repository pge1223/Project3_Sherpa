<!-- 작성자: 경이 / 목적: review_output 스키마 v1 -> v2.0.0 개정 제안(팀 회람용) / 참조: review_output.schema.json(v1), review_output.v2.draft.schema.json, 가은 sample_review_result -->

# 회의 결과 계약 v2.0.0 개정 제안 (DRAFT · 팀 동의 전)

- 제안자: 경이 (contracts/schemas 오너)
- 상태: **제안 단계** — 팀 동의 전까지 확정 아님. v1은 그대로 유지 중.
- 관련 파일
  - 현 계약(v1): `contracts/schemas/review_output.schema.json` (`schema_version: "1.0"`)
  - 제안 드래프트: `contracts/schemas/review_output.v2.draft.schema.json` (`"2.0.0"`)
  - 검증 통과 예시: `ai/meeting/tests/fixtures/final_meeting_result.v2.json`
  - 촉발 계기: 가은 제공 `final_meeting_result.json` (`sample_review_result 1.0.0`)

## 1. 배경 / 문제

가은이 제공한 `sample_review_result` 설계가 현 확정 계약(v1)과 **필드·구조가 전면 다르다.** 둘 중 하나를 그냥 쓰면 계약이 깨진다. 검토 결과, 가은 설계에 v1보다 나은 요소가 많으나 **`media_script`(재인 입력)가 누락**되고 **MTG-003 '필수항목 누락 감점'이 없으며** enum/버전 규칙을 벗어난다. 따라서 두 설계를 통합한 **v2 정식 개정**을 제안한다. 현재 백엔드·프론트에 계약 의존 코드가 없어 **개정 비용이 가장 낮은 시점**이다.

## 2. 제안 요약 (v2에서 흡수/신설)

| 구분 | 내용 | 출처 |
|---|---|---|
| 신설 | `rubric` 블록 (항목별 `max_score`·`required`·`description`) | 가은 |
| 신설 | `rubric_scores[].judgment` (strong/acceptable/needs_improvement/critical_risk) | 가은 |
| 신설 | `reviewer_results[].cross_reviews` / `out_of_scope` (핸드오프) | 가은 |
| 신설 | `chair_summary` 풍부화 (overall_assessment·top_strengths·top_risks·decision_note) | 가은 |
| 신설 | `score_result.calculation_method` = **criterion_owner** (배점 기반, 항목별 담당 위원 채점) | 가은 |
| 신설 | `score_result.penalties[]` (필수항목 누락 감점) | **MTG-003 (경이)** |
| 유지 | `media_script` (재인 입력) — 가은 파일서 누락된 것 **복구** | v1 |
| 유지 | 중앙 `evidence[]` + `evidence_ids` 참조 (가은 인라인 quote/relevance는 evidence 항목에 흡수) | v1 + 가은 |
| 유지 | `domain`/`status` enum, `score_label` const | v1 |
| 변경 | `schema_version` `"1.0"` → **`"2.0.0"`** (구조 변경 = major) | 규칙 |

## 3. 주요 필드 매핑 (v1 · 가은 · v2)

| v1 | 가은(sample) | v2 (제안) | 비고 |
|---|---|---|---|
| (없음) | `rubric.criteria[]` | `rubric.criteria[]` (+`required`) | 배점표 명시 |
| `reviewer_results[]` | `reviews[]` | `reviewer_results[]` | 이름은 v1 유지 |
| `rubric_scores[].score` | `review_items[].score_recommendation` | `rubric_scores[].score` | |
| `.issues` / `.suggestions` | `.weaknesses` / `.improvement_actions` | `.issues` / `.suggestions` | v1 이름 유지(하위영향 최소) |
| (없음) | `.judgment` | `.judgment` | 신설 |
| `evidence[]`+`evidence_ids` | `evidence_refs[]`(인라인) | `evidence[]`(+`quote`,`relevance`)+`evidence_ids` | 중앙화 유지 |
| `score_result.breakdown[].weight`/`weighted_score` | `score_engine_result.criteria_scores[].final_score`+`source_review_ids` | `breakdown[]`에 둘 다 포함(+`source_review_ids`,`penalty`) | 두 모델 표현 |
| `agreements[]` | `chair_summary.consensus[]` | `chair_summary.consensus[]` | 흡수 |
| `disagreements[]` | `chair_summary.disagreements[]` | `chair_summary.disagreements[]` | 이동 |
| `top_revisions[]` | `chair_summary.final_priority_actions[]` | `top_revisions[]`(+`related_criteria`) | v1 위치 유지 |
| **`media_script[]`** | (없음) | **`media_script[]`** | **복구** |

## 4. 점수 모델 결정 (MTG-003 직접 관련)

- 방식: **criterion_owner** — 각 평가항목은 담당 위원 1명이 채점하고, 항목 `max_score`가 곧 배점(가중치) 역할.
- 총점 = Σ(항목 점수) − Σ(penalty). 예시: 20+18+11+12 − 0 = **61 / 100**.
- 필수항목(`required: true`) 미제출/미평가 시 `penalties[]`에 `missing_required` 감점을 기록 → RPT-006 점수 설명에 그대로 재사용.
- `weighted_average`(v1 방식)도 `calculation_method`로 남겨 선택 가능.

## 5. 영향 범위 / 협의 대상

| 담당 | 영향 | 필요 확인 |
|---|---|---|
| **재인** | `media_script` 유지되나, 상위 구조가 바뀜 | 발언 스크립트 접근 경로만 확인(그대로 `media_script[]`) |
| **윤한** | DB 저장·리포트 API 응답 구조 변경 | 저장 문서 형태·인덱스 영향 검토 |
| **가은** | 프론트 리포트 UI가 v2 구조 소비 | 필드명 최종 합의(특히 issues/weaknesses) |
| **경이** | 점수 엔진(M2)·LangGraph 출력이 v2 기준 | 본 제안 주관 |
| 용준 | 간접(evidence.source_type 등) | 영향 시에만 |

## 6. 팀 변경 절차 체크리스트 (docs/04_TEAM_WORKFLOW.md §5)

- [x] 변경 제안 작성 (본 문서)
- [x] JSON 예시 공유 (`final_meeting_result.v2.json`, 검증 통과)
- [ ] 영향 담당자 확인 (재인·윤한·가은)
- [ ] 팀 동의
- [ ] `schema_version` 갱신 및 v1 → v2 교체 (`review_output.schema.json`)
- [ ] Mock(`contracts/mocks/`)·테스트·문서 갱신
- [ ] 코드 반영 (M2 점수 엔진은 v2 기준으로 착수)

## 7. 미해결 질문 (팀 논의)

1. 필드명 `issues/suggestions`(v1) vs `weaknesses/improvement_actions`(가은) — 최종 채택?
2. `cross_reviews`는 **2차(round≥2)에서만** 허용해 MTG-001 '독립평가' 제약과 충돌 방지 — 동의?
3. 필수항목 누락 감점 규칙(감점 폭)을 rubric에 둘지, 별도 `meeting_rules.json`에 둘지?
