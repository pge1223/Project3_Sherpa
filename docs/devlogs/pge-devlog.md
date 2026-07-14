# pge Devlog

## 2026-07-14

- 한 일:
  - 레포를 지원금 셰르파 → AI Review Board로 전면 리셋 (main/dev 히스토리 초기화)
  - CLAUDE.md 및 팀 워크플로 문서 정리, `feature/pge` 통해 PR
  - `docs/`, `contracts/`, `frontend/`, `backend/`, `ai/` 등 모노레포 폴더 스캐폴딩
  - frontend에 Vite+React 기본 골격 추가, `npm run dev` 로컬 확인 완료
  - `environment.yml`이 `requirements.txt` 없어서 `conda env create` 실패하는 문제 발견 → 최소 의존성으로 `requirements.txt` 추가, `fix/requirements-txt` 브랜치로 PR
  - 페르소나·프롬프트 관련 추가한 파일 구조:

    ```text
    ai-review-board/
    ├─ ai/
    │  └─ meeting/
    │     └─ personas/
    │        ├─ persona_cards.json                        # 전문가 라이브러리 9인(공통 2 + 도메인별 2×3 + 위원장)
    │        ├─ startup.json                               # 스타트업형 위원 구성 + meeting_culture
    │        ├─ government_support.json                    # 정부지원사업형 위원 구성 + meeting_culture
    │        ├─ competition.json                           # 공모전형 위원 구성 + meeting_culture
    │        └─ rubric_mapping_government_support.json     # PER-002 정부지원사업 rubric 매핑 샘플
    │
    ├─ docs/
    │  └─ prompts/                                         # 기획 초안(실행 파일 아님)
    │     ├─ common_reviewer_prompt.md
    │     └─ persona_prompts.md
    │
    └─ contracts/
       └─ mocks/
          ├─ final_meeting_resault.json
          └─ notice_criteria_government_support.json       # 용준 포맷 공고문 평가기준 mock
    ```
  - PER-001(도메인별 위원 템플릿 구성): `persona_cards.json`에 도메인 특화 위원 6명(marketing_growth, investment_readiness, policy_fit, budget_execution, creativity_originality, presentation_completeness) + 위원장(review_chair) 추가, 도메인별 4명+위원장 구성 파일 3개 작성
  - PER-002(공고 기반 평가축 보정): 정부지원사업 도메인만 우선 샘플로 `rubric_mapping_government_support.json` 작성 (startup·competition은 아직)
  - PER-003(도메인별 회의 순서·문화): 도메인 구성 파일 3개에 `meeting_culture`(tone, pace, 위원장 질문 초점, 개입 방식, guardrails) 추가
  - `common_reviewer_prompt.md`/`persona_prompts.md`를 `ai/meeting/prompts/`(경이 실행 파일 자리)에서 `docs/prompts/`(가은 기획 초안 자리)로 이동 — 소스폴더구조 가이드 3장 컨벤션에 맞춤
  - 로그인 화면(`LoginPage`) 구현, 실제 백엔드 `/auth/login`(bcrypt + JWT)과 연동해서 회원가입→로그인→토큰 발급까지 실제 DB로 검증
  - `ai_review_board` MongoDB가 어디에도 안 떠 있어서, `sherpa_mongo`가 있는 서버(`220.81.7.136`)에 SSH 터널로 임시 연결 — `scripts/export_sherpa_raw_data.py`로 K-Startup/기업마당 원시 공고 데이터(29,410 + 3,178건)도 export
  - `ProjectListPage`(내 프로젝트 목록), `DocumentUploadPage`(`/projects/new`, 문서 업로드) 구현 — 시안 이미지 기반, 실제 파일 선택 + 드래그앤드롭 동작, 임베딩 진행률 시뮬레이션
  - 전체 화면 밝은 하늘색 테마로 통일 (로그인/프로젝트목록/상세/업로드), 로고(`logo1.png`) 적용, "← 뒤로"·"분석 시작" 버튼 추가
  - PR #14(용준) 확인 → URL 공고문 가져오기용 FastAPI 엔드포인트가 아직 없는 것 확인, 용준에게 전달할 요청(`POST /documents/fetch-url`) 정리
- 결정/이유:
  - `.gitignore`의 `models/` 규칙이 `backend/app/models/` 코드 폴더까지 가려서 `ai/**/models/`로 좁힘
  - `requirements.txt`는 배포용 공통 파일이라 최종본은 윤한과 상의 필요 — 지금은 로컬 개발 unblock용 최소 버전만 커밋
  - `requirements.txt`에 `python-jose`, `bcrypt`, `email-validator` 누락 발견 (PR #12 코드는 쓰는데 목록엔 없었음) → 추가
  - `Settings` 클래스가 선언 안 된 `.env` 필드를 만나면 통째로 기동 실패하는 걸 발견 → `backend/.env`는 필요한 필드만 최소로 유지
  - sherpa_mongo 서버는 이름만 안 바뀌었을 뿐 계속 재사용하기로 팀 확인함
  - 위원장(review_chair)은 다른 위원과 입출력 스키마가 달라서 `common_reviewer_prompt.md`와 결합하지 않기로 함 — 실제 결합은 경이가 만들 별도의 `chair_prompt.txt` 몫으로 남김
  - 정부지원사업 도메인 위원 구성에서 "정책부합성" 항목은 전용 위원이 없어 일단 business_strategy에 배정 — 위원이 3인 이상으로 늘면 재검토 필요하다고 `mapping_note`에 남겨둠
- 막힌 점:
  - 로컬에 `gh` CLI가 없어서 PR은 커맨드로 못 열고 compare 링크로 대체
  - 커밋 안 된 frontend 파일들이 브랜치 정리 중 여러 번 사라짐 — untracked 파일은 `git stash`에 기본으로 안 담긴다는 걸 다시 확인
  - 같은 이유로 `ai/meeting/personas/`, `docs/prompts/` 작업 파일도 세션 중 브랜치가 여러 번 바뀌면서 사라졌다가, `feature/pge-frontend-personas`에 이미 커밋되어 있던 걸 확인하고 `git checkout <branch> -- <path>`로 필요한 파일만 복구함
  - Vite dependency 캐시가 stale해져서 "React is not defined" 에러가 반복 발생 → `node_modules/.vite` 캐시 삭제로 해결
  - SSH 프라이빗 키(`review_board_ssh-key.pem`)가 실수로 레포 폴더 안에 저장되어 있던 걸 발견 → `~/.ssh/`로 옮기고 `.gitignore`에 `*.pem`/`*.key` 추가
- 다음 할 일:
  - `fix/requirements-txt` PR 팀 리뷰 받기
  - frontend 실제 페이지(로그인/업로드/회의실/리포트) 작업 이어가기
  - 용준에게 URL 가져오기 엔드포인트(`POST /documents/fetch-url`) 요청
  - 문서 업로드 API, 프로젝트 목록 API를 Mock에서 실제 백엔드로 교체
  - `ai_review_board` MongoDB 정식 위치를 윤한과 상의 (지금은 sherpa_mongo 서버에 임시로 얹어놓은 상태)
  - PER-002 rubric 매핑을 startup·competition 도메인까지 확장
  - PER-004(Persona Card 버전 관리 정책) 착수
  - 경이에게 `docs/prompts/*` 넘기고 `ai/meeting/prompts/{prompt_loader.py,reviewer_prompt.txt,chair_prompt.txt}` 변환 요청
  - 오늘 작업(persona_cards.json 등) `feature/pge` 브랜치에 커밋
