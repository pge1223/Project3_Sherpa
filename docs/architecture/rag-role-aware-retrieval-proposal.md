# RAG 역할 기반 검색(Role-Aware Retrieval) 위원회 연동 제안

- 상태: **설계 논의 필요 (Draft, 미착수)** — 아래 1번·3번은 구현 전 팀 확인 필요
- 작성: 가은/Claude, 2026-07-17
- 관련 담당: 용준(RAG, `ai/rag/role_retrieval`), 경이(LangGraph 회의 그래프, `ai/meeting/graph`)
- 계기: "사업전략 전문가 멘토는 그에 맞는 전문 지식이 있어야 하는데, RAG 앞에
  페르소나별 프롬프트를 태워서 그 위원 관점에 맞는 근거를 검색 후 피드백하게 할 수
  있는가?" (가은)

## 배경

지금 `analyze_project()`(`backend/app/api/routes/meetings.py`)는 rubric의 각 채점
기준(criterion_name)으로 RAG 검색을 1번씩 돌려 결과를 **하나의 공용 evidence
리스트**로 합친다. 이 리스트를 위원 전체가 그대로 나눠 받고, "본인 전문 범위만
상세히 검토하라"는 지시는 `reviewer_prompt.txt`의 프롬프트 레벨 지시로만 이뤄진다
— 즉 검색 자체는 위원 역할과 무관하게 동일하다.

반면 용준님이 이미 `ai/rag/role_retrieval/`(RAG-003)에 **역할 인지 검색** 모듈을
만들어뒀다:
- `RoleAwareRetrievalService.search_by_role(query, project_id, role_id, ...)`
- `role_id`별로 검색 질의를 확장(`query_builder.build_expanded_query` — LLM 호출
  없음, 규칙 기반으로 역할 지침 문장을 질의 앞에 붙임)
- 결과를 역할 키워드 매칭 점수로 재정렬(`reranker.rerank_by_role`)
- 단, 이건 **이 프로젝트가 이미 색인해둔 문서(기획서+공고문) 안에서** 그 역할
  관점에 더 맞는 부분을 찾아주는 것이지, 외부 경영학 지식 같은 걸 새로 가져오는
  게 아니다 — 범위를 정확히 해둘 필요가 있다.

## 이미 완료된 것 (2026-07-17, 배선만 교체 — 동작 변화 없음)

`_search_evidence_for_rubric()`이 `RAGIndexingService.search()`를 직접 부르던
것을 `RoleAwareRetrievalService.search_by_role(role_id=None)`로 교체했다.
`role_id=None`이면 `build_expanded_query()`가 질의를 그대로 반환하고
`rerank_by_role()`의 role_score도 항상 0이라(`ai/rag/role_retrieval/reranker.py`),
결과는 기존 semantic-score-only 검색과 순위가 동일하다 — 지금은 실질적인 동작
변화가 없는 **"활성화 대기 상태의 배선 교체"**다. 아래 1번(역할 매핑)이 정해지면
이 함수(또는 호출부)에 role_id만 채워 넣으면 바로 켤 수 있다.

## 논의가 필요한 것

### 1) persona_id ↔ role_id 매핑 (용준님)

지금 `RoleRegistry`(`ai/rag/role_retrieval/roles.py`)엔 4개 역할만 있다:
`finance` / `technology` / `marketing` / `planning`. 우리 위원 persona_id
(`ai/meeting/personas/persona_cards.json`)는 8종 + 위원장이라 이름이 안 맞는다.

| persona_id | 후보 매핑 | 비고 |
|---|---|---|
| business_strategy | planning | |
| technical_feasibility | technology | |
| marketing_growth | marketing | |
| investment_readiness | finance | |
| policy_fit | ? | 기존 4종에 없음 — 신규 role 후보 |
| budget_execution | finance | investment_readiness와 겹침, 구분 필요할 수도 |
| creativity_originality | ? | 기존 4종에 없음 — 신규 role 후보 (competition 전용) |
| presentation_completeness | ? | 기존 4종에 없음 — 신규 role 후보 (competition 전용) |
| review_chair | (역할 검색 대상 아님) | 위원장은 종합 역할이라 role_id 불필요할 가능성 |

**결정 필요**: 기존 4종을 억지로 재사용할지, `policy_fit`/`creativity_originality`/
`presentation_completeness`용 신규 role을 `roles.py`에 추가할지. 신규 role을
만든다면 `focus_keywords`/`section_keywords`/`query_instruction`의 정확도는
RAG 검색 품질에 직결되니 용준님 판단이 필요하다.

### 3) 그래프 상태에 위원별 evidence 반영 (경이님, 변경 범위 큼)

`run_meeting()`은 `retrieved_evidence: list[dict]` 하나를 받아
`initial_state()`에 그대로 넣고, `assemble_meeting_graph()`가 만드는 모든
`reviewer__{persona_id}` 노드가 같은 `state["evidence"]`를 공유해서 읽는다
(`ai/meeting/graph/build.py`, `state.py`). 위원별로 다른 evidence를 주려면:

- `MeetingState`에 `evidence_by_persona: dict[str, list[dict]]` 같은 필드
  추가(기존 `evidence` 필드와의 하위호환 여부 결정 필요)
- `make_reviewer_node(persona_id, ...)`가 `state["evidence"]` 대신
  `state["evidence_by_persona"][persona_id]`를 읽도록 수정
- `run_meeting(retrieved_evidence=...)` 시그니처가 `dict[str, list[dict]]`를
  받도록 변경
- `rerun_reviewer()`(단일 위원 재평가 경로)도 같은 모양으로 맞출지 결정 필요

이건 그래프 설계를 직접 바꾸는 작업이라 리스크가 크다 — 경이님과 먼저 방향에
동의를 구한 뒤 착수해야 한다.

## 제안하는 순서 (리스크 작은 순)

1. (완료) 검색 호출을 `RoleAwareRetrievalService`로 교체, `role_id=None`으로
   동작 무변화 확인
2. 1번(역할 매핑) 확정 — 용준님
3. 위원별로 **검색은 하되 결과는 합쳐서** 하나의 evidence 리스트로 넘기는
   절충안 시도 — 그래프 구조는 안 건드리고 검색 다양성만 확보. 이러면 3번
   (그래프 변경) 없이도 부분적 효과를 먼저 확인할 수 있다.
4. 3번(그래프에 위원별 evidence 분리 전달) 착수 — 경이님과 설계 합의 후.
   2에서 효과가 미미하면 굳이 안 해도 됨(비용 대비 효과 재평가).

## 리스크/트레이드오프

- 새 LLM 호출은 없다(쿼리 확장이 규칙 기반) — 비용/속도 영향 없음
- `candidate_k`가 `top_k * 3`이라 벡터 검색 자체는 약간 늘어남(무시할 만한 수준)
- 신규 role 키워드 세트가 부실하면 오히려 관련 없는 청크가 위로 올라올 수 있어,
  `focus_keywords`/`section_keywords` 구성 품질이 중요함
