# mky Devlog

## 2026-07-21

- 한 일:
  - **버전 추적형 User RAG = 개인 맞춤형 피드백 루프** 프론트 실험 화면(`/version-test`) 신설
    (`frontend/src/pages/VersionTrackerTestPage.jsx` + `VersionTrackerTest.css`). 내 백엔드
    산출물을 화면으로 검증하는 용도 — 각 버전 위원 피드백은 `review_output.reviewer_results`,
    버전 간 증감·해결/잔존/신규는 **내 RPT-004 `build_revision_comparison()`** 출력 구조를
    그대로 mock으로 넣음(백엔드 연동 시 mock만 실데이터로 교체)
  - 기능: v1.0→v1.3 **버전 누적 제출**(하나씩 reveal) + **위원 탭 분리**(기획/개발) +
    **이전 vs 현재 막대 비교** + **점수 추이 라인차트**(SVG) + 카운트업/막대/라인 애니메이션
  - **개인화 입력**: 수정본(기본) + GitHub + 이력·교육수준 제출, **TEST 프로필 토글**(비전공자/전공자).
    개발 위원 피드백을 프로필에 따라 다르게 — 비전공자=`구현 난이도 어려울 수 있음`+`자세히 보기`
    (단계별 상세), 전공자=`쉬움`+간결한 한 줄
  - dev 최신화(가은 서비스 방향전환 리디자인 `/board` 프로토타입 + 용준 ideation 병합) 반영,
    `feat(frontend) TEST 섹션` 커밋(`f2f3694`) 푸시
- 결정/이유:
  - **격리 원칙 유지**: `/board`·StepSidebar 등 가은 프론트 코드 미수정, `App.jsx` 라우트 1줄만
    추가. 실험 검증 후 정식 플로우(`/board` 프로젝트 리포트) 이어붙일 때 가은과 배치 협의 예정
  - **디자인 톤을 가은 새 `.rb-root`(웜 화이트/글래스, 퍼플·코랄·그린·앰버, mono, lucide)에 1:1**
    맞춤 — 나중에 이어붙일 때 이질감 0
  - **RPT-004 재활용이 핵심 메시지**: "1회성 챗봇과 달리 수정 이력을 기억해 점수 상승세·지적 해결을
    추적"을 시각적으로 보여줘, 내 비교 로직이 제품 차별점으로 직결됨을 시연
- 막힌 점:
  - 새 디자인이 `lucide-react`를 쓰는데 node_modules 미설치 상태여서 `/board`도 안 뜸 →
    `npm install`로 해결. `Github` 아이콘은 lucide 1.x에서 브랜드 아이콘 삭제로 없어서 `GitBranch`로 교체
  - 막대가 점수 비율과 무관하게 꽉 차 보이던 버그 — 채워지는 div에 `height`가 없어 0px(빈 트랙만
    보임)이었음. `height:100%` 지정으로 수정
- 다음 할 일:
  - 실제 연동: 프로젝트당 회의(버전) 다건 저장·목록 조회 API(윤한) → mock을 실데이터로 교체
  - 개인화 입력(GitHub/이력) 실제 파싱·프로필화는 별도 논의(현재는 프론트 mock 프로필 2종)
  - 가은 새 디자인 정식 플로우에 버전 히스토리 탭으로 이어붙이기 협의

## 2026-07-16

- 한 일:
  - **RAG-003/004/005 회의 연동**(용준 어댑터): `run_meeting`/state/build에 `evidence_context`(persona·criterion별 근거+사전 sufficiency) + `evidence_callback`(backend 주입) optional 추가. reviewer 노드가 ①사전 prompt_guard 삽입 → ②의견 생성 → ③criterion별 콜백(RAG-004 링크+RAG-005 최종판정) → ④A안(근거를 RAG-004로 교체) + `allow_numeric_score=False` 게이팅. EvidencePool에 `(document_id, chunk_id)→evidence_id` 역조회(`register_linked`) 추가. `<<EVIDENCE_GUARD>>` 토큰 신설. **전부 backward-compatible**(인자 없으면 기존 flat 경로 그대로)
  - 용준 실제 어댑터 출력 샘플(`rag_adapter_samples.json`)로 통합 테스트 — `MeetingLinkedEvidenceRef`가 v2 evidence로 정확 매핑(text 없는 건 retrieved에서 보강) + run_meeting E2E 검증
  - **review_output v2.1.0 계약 개정**(팀 동의 후): 선택 필드 `similar_success_cases`(RAG-006 유사사례, reference_only) 추가, `schema_version` const→enum `["2.0.0","2.1.0"]`(하위호환). `run_meeting`/`assemble_document` pass-through, 신규 문서 "2.1.0"
  - **TST-002 위원 일관성 하네스**(`ai/meeting/quality/consistency.py`): 반복 평가 편차(총점/항목 점수/judgment 일치율/핵심 지적 Jaccard) 측정 + 허용범위(`ConsistencyTolerance`) 위반 판정. v2 문서만 읽어 실행 방식 비의존(DI)
  - 테스트 40개 통과(scoring 5 + explanation 4 + comparison 3 + graph 9 + rerun 2 + reevaluate 2 + evidence_integration 8 + consistency 7). **내 담당 요구사항(MTG-001~004/006/007, RPT-004/006, TST-002) 코드 전부 완료**
- 결정/이유:
  - **회의 파이프라인 ↔ RAG decoupling 유지**: 그래프가 `ai.rag`를 직접 import하지 않고, backend가 판정 결과·근거를 plain data(evidence_context) + Callable(evidence_callback)로 주입. RAG 스키마가 바뀌어도 회의 코드가 안 깨짐
  - **RAG-004 A안(위원 자기보고 근거 폐기, RAG-004 링크만 사용)** + 게이팅은 `(persona, criterion)` 단위 — 용준과 계약 확정
  - **similar_success_cases는 permissive(내부 재검증 안 함) + 최상위 + schema_version enum**: RAG-006이 진행 중이라 계약을 용준 스키마에 안 묶고, 기존 "2.0.0" 문서도 유효하게 유지
  - **일관성은 '완전 일치'가 아니라 '허용 편차 정의+측정'**(생성 모델 특성상 완전 동일 요구 금지). 실제 모델 붙기 전엔 stub으로 파이프라인 결정론(편차 0) baseline 확인
  - 공용 계약 변경(v2.1.0)은 팀 절차대로: 제안서(`review_output.v2.1.proposal.md`) → 재인/윤한/가은/용준 동의 → 적용
- 막힌 점:
  - 가은이 실제 OpenAI 호출로 `assemble_document`의 persona_id 버그를 잡아줌(LLM이 지어낸 persona_id를 못 믿어 딕셔너리 키로 덮어쓰게 수정) — 내 stub 테스트로는 안 잡혔던 것. 회귀 가드 테스트 추가 예정
  - 용준 어댑터 출력은 **persona별 flat**인데 내 `evidence_context`는 `(persona,criterion)별+sufficiency` 묶음이라, 그 사이 조립 헬퍼(`build_evidence_context`)가 필요 → RAG-005 사전 sufficiency granularity 확인 후 추가 예정
  - dev가 하루에 #46~#57까지 빠르게 머지돼(로깅·HWP·RAG-006·backend 실연결 등) push 전마다 재싱크 반복
- 다음 할 일:
  - `build_evidence_context` 헬퍼(용준 회신 대기) / 가은 모델명 확정 후 실제 LLM E2E / 실제 모델로 일관성 편차 실측
  - `assemble_document` persona_id 회귀 가드 테스트
  - RPT-004/006 화면(가은)·evidence_context 조립·API(윤한) 연동 지원

## 2026-07-15

- 한 일:
  - **rubric_mapping_government_support 4인 확장**: 회의 진행 위원회를 government_support.json과 동일한 4인(policy_fit·business_strategy·technical_feasibility·budget_execution)으로 맞추고, policy_alignment→policy_fit·execution_plan→budget_execution 재배정, `required:true`(source:notice) 반영 (#27)
  - **M3 LangGraph State**: 회의 1회 공유 상태(TypedDict) 정의. reviewer_results/evidence에 병렬 fan-in 병합 리듀서를 둬 위원 결과 유실 방지 (#30)
  - **M4 노드+그래프 조립**: reviewer(위원별 독립 병렬) → score(M2 계산 엔진 연결) → chair(종합+top_revisions) 노드, rubric_mapping→v2 rubric 변환기, 위원 raw(judgment 6종)→v2 reviewerResult(4종) 변환기, EvidencePool. LLM은 인터페이스만 분리하고 stub으로 테스트 (머지됨)
  - **실제 LLM 연동 + 엔트리포인트**: `make_openai_llm_call`(모델명 필수 인자로 강제), `run_meeting`(rubric_mapping+문서→v2 결과 조립). backend가 analyze() 내부만 교체하면 되게 시그니처 맞춤
  - **MTG-006 완성**: `run_meeting(on_progress=...)` 진행률 통지 + `assemble_meeting_graph(checkpointer=...)`로 실패 노드부터 재시도
  - **RPT-006**: `build_score_explanation` 점수 설명 카드 로직(계산값에서만 설명 생성)
  - **MTG-007**: `rerun_reviewer` 특정 위원만 재평가+재종합, 나머지 위원 결과 유지
  - **RPT-004**: `build_revision_comparison` 수정 전후 비교(항목별 증감·해결/신규 지적, 평가기준 변경 시 직접 비교 제한)
  - `contracts/mocks/final_meeting_result.v2.json` 추가(가은 프론트 스텁 API용, v2 검증 통과). 기존 `final_meeting_resault.json`은 v2 이전(17개 위반)이라 쓰지 말 것으로 가은에게 전달
  - 테스트 총 23개(scoring 5 + explanation 4 + comparison 3 + graph 9 + rerun 2) 통과
- 결정/이유:
  - **required 필드 v2 표준은 경이가 확정**(가은 위임): source:notice 항목은 전부 required:true, default_supplementary_perspectives는 채점 제외. 관련 파트(윤한·용준·가은)에 공유
  - **government_support 회의 과정=4인 / 영상 MVP=2인**: 4인으로 평가·종합하되 media_script는 2인분만(테스트 후 4인 확장 예정)
  - **점수/설명/비교 리포트는 LLM이 아니라 계산값에서만 생성**: RPT-006 예외("LLM 자연어와 계산값 불일치 방지")를 구조적으로 차단 — 카드의 어떤 수치도 M2 출력과 어긋날 수 없음
  - **위원 raw 출력 스키마는 가은 초안 그대로 유지, v2 변환은 경이 노드가 전담**(담당 경계). judgment 6종 중 insufficient_evidence/not_applicable은 rubric_scores에서 제외 → M2 누락 감점 로직이 자연 처리
  - **chair_prompt.txt의 final_priority_actions에 title/target/reason/evidence_ids 보강**: 기존 스키마로는 MTG-004 검수 기준("이유·대상 문단 제시")을 못 지켜서 실행 프롬프트 자체를 수정
- 막힌 점:
  - LangGraph 노드 이름에 `:` 예약문자 불가 → `reviewer__{persona_id}`로 변경
  - openai 패키지 미설치 → requirements.txt에 추가. 실제 사용 모델은 가은이 비용/품질 검토 중이라 `make_openai_llm_call` model을 기본값 없는 필수 인자로 둠
- 다음 할 일:
  - **TST-002 위원 일관성 테스트**(내 담당 마지막 요구사항): 반복 실행 편차 측정 하네스. 실제 편차는 LLM 붙어야 의미 있으므로 stub으로 파이프라인 결정론 baseline부터
  - 윤한: 진행률/재시도/재실행 API 연결, RPT-004 두 회의 조회, meetings.py 스텁을 run_meeting 호출로 교체
  - 가은: RPT-006 점수 설명 카드·RPT-004 비교 리포트 React 화면
  - RPT-004/006은 로직 완료, 화면·DB 연결만 남음

## 2026-07-14

- 한 일:
  - CLAUDE.md / `docs/*.md` 정독 후 경이 담당(LangGraph·점수 엔진·평가 결과 구조) 마일스톤 스케줄 수립 (M0 환경 → M1 Mock → M2 점수 엔진 …)
  - `review-board` conda env 생성 (Python 3.12 + langgraph/jsonschema/pytest), import 검증 완료
  - **M1**: `ai/meeting/tests/fixtures/`에 회의 결과 Mock(reviewer_result / final_meeting_result / rag_response) 작성 + jsonschema 검증 통과 → PR #13으로 dev 머지
  - **review_output v2.0.0 계약 개정 제안**: 가은 `sample_review_result` 설계를 통합(rubric 배점표 / judgment / cross_reviews / 풍부한 chair_summary / criterion_owner 채점), `media_script` 유지(재인), MTG-003 필수항목 누락감점(penalties) 반영 → #13에 포함, 팀(가은·윤한·재인) 승인
  - 가은 `docs/prompts` 초안 → `ai/meeting/prompts/` 실행 파일 3종 변환: `reviewer_prompt.txt`, `chair_prompt.txt`, `prompt_loader.py` (+ `__init__.py`), 스모크 테스트 통과
  - **M2 점수 엔진** `ai/meeting/scoring/`: `calculator.py`(criterion_owner·Decimal 결정론), `weights.py`, `deductions.py`(누락감점) + `tests/test_scoring.py` **pytest 5개 통과**(mock 재현 총점 61·동일입력=동일출력·누락감점)
- 결정/이유:
  - 점수 모델은 **criterion_owner**(배점=가중치) 채택 — 실제 심사 방식에 가깝고 MTG-003 "가중합" 요건 충족. 점수는 LLM이 아니라 Python 규칙으로만 계산해 재현성 보장
  - reviewer/chair 실행 프롬프트는 **가은 초안 출력 스키마 그대로 유지**하고, v2 계약으로의 변환은 경이 LangGraph 노드(M4)에서 처리하기로 함 — 가은 설계 보존 + 담당 경계 유지(위원 원본→v2 매핑은 경이 코드 몫)
  - 페르소나 프롬프트 prose는 중복 저장하지 않고 `persona_cards.json`에서 렌더링 → 카드만 고치면 프롬프트 자동 반영(drift 방지)
  - 공통 계약(`review_output.schema.json` v1→v2 교체)은 프롬프트·M2와 **분리해 별도 PR**로 — 계약 변경은 재인·윤한·가은 리뷰가 필요하기 때문
- 막힌 점:
  - dev가 반나절에 #13~#20까지 빠르게 머지돼 push 직전마다 재싱크 필요 — fetch → `git merge origin/dev` 반복으로 대응(내 담당 영역과 충돌은 없었음)
  - `conda run -n review-board`가 한글 stdout에서 cp949 인코딩 에러 → env python 직접 호출 + `PYTHONUTF8=1`로 우회
  - JSON은 주석 불가 + 스키마 `additionalProperties:false`라 Mock 파일 헤더를 `_meta` 블록/README로 대체
- 다음 할 일:
  - v1→v2 스키마 교체 + 드래프트 스키마 제거 + `contracts/mocks` 승격(가은 페르소나/rubric 반영)을 계약 PR로 올리기
  - M3~M5: LangGraph State·노드(reviewer_a/b·score·chair·media_script)·그래프 조립
  - 위원 원본(raw) → v2 `reviewerResult` 매핑 노드 구현
  - TST-002 위원 일관성 테스트 본격화
