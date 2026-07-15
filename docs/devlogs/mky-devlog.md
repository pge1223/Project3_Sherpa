# mky Devlog

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
