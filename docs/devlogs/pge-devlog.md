# pge Devlog

## 2026-07-16

- 한 일:
  - (Claude Code와 세션) 로컬 `dev`를 브랜치 전환 없이 `git fetch origin dev:dev`로 두 차례
    최신화 — PR #36("평가 의견과 원문 출처 및 근거 연결", `ai/rag/evidence_linking/*`),
    PR #37("실제 LLM 연동 + 회의 실행 엔트리포인트 추가" + MTG-006 진행률/재시도) 반영
  - (Claude Code와 세션) `dev`를 `feature/pge`에 merge. git 커밋 레벨 충돌은
    `ai/meeting/graph/__init__.py` 하나뿐이었고(양쪽이 서로 다른 export를 추가한 것뿐이라
    둘 다 살려서 합침), 나머지는 겹치는 파일이 없어 깔끔하게 합쳐짐
  - (Claude Code와 세션) merge 이후 **기능적 중복 발견 및 정리**: PR #37로 들어온 경이의
    `ai/meeting/graph/run.py`(`run_meeting()`)/`rerun.py`(`rerun_reviewer()`)가, 우리가
    M4 전에 임시로 만들어둔 `analyze_project()`/`reevaluate_reviewer()`의 직접 그래프 조립
    로직(+ 우리가 만든 `ai/meeting/graph/reevaluate.py`, MTG-007용)과 같은 역할을 하고
    있었음. `run.py` 주석에 "analyze_project()가 이 함수 하나만 호출하면 되도록 만들었다"고
    명시돼 있어, 우리 임시 구현을 걷어내고 경이 버전으로 교체함:
    - `backend/app/api/routes/meetings.py`: `analyze_project()`/`reevaluate_reviewer()`
      내부를 `run_meeting()`/`rerun_reviewer()` 호출로 교체. 걷어낸 우리 코드(그래프 직접
      조립, `_reviewer_results_to_list()`, `_document_to_meeting_state()`)는 삭제 대신
      주석 처리하고 교체 사유를 각 자리에 남김(파일 상단 docstring에도 정리)
    - `backend/app/models/meeting.py`: `document_id` 필드 추가 — `rerun_reviewer()`가
      `previous_document["document_id"]`를 요구해서 필요해짐. **이 필드 추가 전에 저장된
      기존 `meetings` 레코드는 `document_id`가 없어 그 레코드로 재평가하면 KeyError 위험**
    - `ai/meeting/graph/reevaluate.py`: 더 이상 안 쓰인다는 주석만 추가, 파일 자체는 삭제
      안 함(경이 확인 후 삭제 여부 결정)
  - 넘겨야 할 미해결 문제 2가지(코드에도 주석으로 남겨둠) — 아래 "e2e 검증" 참고, 1번은
    이후 실제로 재현·수정까지 완료:
    1. 경이의 `run.py`/`rerun.py`의 `assemble_document()`가 `reviewer_results`를
       `list(final_state["reviewer_results"].values())`로 만들어서, 우리가 방어했던
       "LLM이 raw JSON의 persona_id를 지어내는" 버그(2026-07-15 발견)가 재현될 수 있음
    2. `run_meeting()`/`rerun_reviewer()`가 `graph.stream()`에 `recursion_limit`을 넘기지
       않아서, 우리가 쓰던 상한(12)이 지금 경로에선 적용 안 되고 LangGraph 기본값(25)으로
       동작함 (`_MAX_LLM_CALLS_PER_MEETING` 호출 횟수 상한은 `llm_call` 쪽에서 여전히 유효)
  - (Claude Code와 세션) **실제 OpenAI 호출로 e2e 검증** — 브라우저 자동화 도구가 없어서
    curl로 실제 업로드 -> 분석 -> 재평가 흐름을 그대로 재현(소켓 레벨이지만 프론트가
    호출하는 것과 동일한 API). 첫 라운드에서 위 1번 문제가 실제로 터지는 걸 확인함:
    `committee`(신뢰 가능, 4명)와 `reviewer_results`의 persona_id(4개 다 LLM이 지어낸
    값, committee와 하나도 안 겹침)가 analyze() 직후부터 이미 어긋나 있었고, 이 상태에서
    `reevaluate_reviewer()`를 한 번 불렀더니 `rerun.py`의 `kept_results` 필터
    (`r["persona_id"] != persona_id`)가 항상 참이 되어 위원이 교체되지 않고
    `reviewer_results`가 4개 -> 5개로 늘어나는 것까지 실측
  - (Claude Code와 세션) 가은 승인하에 **`ai/meeting/graph/run.py`의 `assemble_document()`
    직접 수정** — `reviewer_results`를 만들 때 v2_result 내부 persona_id 대신
    `final_state["reviewer_results"]` 딕셔너리의 키(committee 기준, 신뢰 가능)로
    덮어쓰도록 변경(우리가 전에 `_reviewer_results_to_list()`로 하던 것과 동일한 방어).
    이 파일은 경이 담당이라 별도로 알려야 함
  - 같은 프로젝트로 재검증: `analyze()` 직후 `reviewer_results` persona_id 4개가
    committee 4명과 정확히 일치, `reevaluate_reviewer()` 호출 후에도 4개 그대로 유지되고
    지정한 위원만 교체됨(5개로 안 늘어남) — 수정 확인 완료. 테스트에 쓴 프로젝트/문서/
    회의 레코드는 전부 삭제해 정리함

- 결정/이유:
  - 두 구현을 나란히 두지 않고 경이 버전으로 완전히 갈아탐 — `run.py` 주석에 이미
    "analyze()가 이 함수만 부르면 됨"이라는 의도가 명시돼 있었고, 회의 실행 로직은
    경이(LangGraph 담당) 소관이라 임시 구현을 계속 유지할 이유가 없다고 판단
  - 삭제 대신 주석 처리 — 왜 걷어냈는지, 무엇으로 교체했는지, 어떤 위험이 남는지를
    코드 자리에서 바로 볼 수 있게 하기 위함(가은 요청)
  - persona_id 버그는 "경이 확인 후" 기다리지 않고 바로 고침 — 실제 호출로 재현까지
    확인된 데이터 정합성 버그라 재평가 기능이 그 전까지는 사실상 못 쓰는 상태였음.
    다만 경이 파일이라 직접 고쳤다는 사실과 이유는 반드시 전달 필요

- 막힌 점 / 협의 필요:
  - `recursion_limit` 미적용(위 2번) — 여전히 안 고침, `run.py`/`rerun.py` 쪽에 config를
    받는 파라미터 추가할지 경이와 논의 필요
  - `ai/meeting/graph/reevaluate.py` 삭제 여부 — 경이 확인 필요
  - `document_id` 필드가 없는 기존 `meetings` 레코드 처리(백필 또는 그냥 무시) — 결정 안 함
  - 이번 e2e 검증은 curl(소켓 레벨)로만 했음 — 실제 브라우저 클릭(로그인 -> 업로드 ->
    "분석 시작" 버튼 -> `MeetingChat.jsx` 렌더링)으로는 아직 확인 안 함

- 다음 할 일:
  - 경이에게 이번에 발견·수정한 persona_id 버그(`run.py`의 `assemble_document()`)와
    recursion_limit 미적용 문제 전달, 특히 persona_id는 경이 파일을 직접 고쳤다는 것부터
    알리기
  - `ai/meeting/graph/reevaluate.py`/`test_reevaluate.py` 삭제 여부 경이와 정리
  - 실제 브라우저로 "분석 시작" → "위원 재평가" 버튼 클릭까지 e2e 확인(지금까지는 curl
    검증만 함)

## 2026-07-15

- 한 일:
  - PR #18(PER-003 meeting_culture + devlog 컨벤션), PR #20(프론트 라우팅/페이지 + sherpa export 스크립트) 머지 확인
  - PR #24(경이, `review_output.schema.json` v2.0.0 구조 변경) 내용 확인 — `rubric`/`chair_summary`/`criterion_owner` 점수모델·penalties 흡수, `media_script` 유지. 우리 쪽 rubric_mapping·페르소나 출력과 당장 충돌은 없음을 확인
  - 로컬 `dev`를 `origin/dev` 기준으로 두 차례 최신화 (PR #24 KURE-v1 임베딩/Chroma 검색 PR #25까지 반영), 브랜치 전환 없이 `git fetch origin dev:dev`로 처리해 `feature/pge` 작업 중이던 미커밋 변경사항은 그대로 유지
  - PER-002(공고 기반 평가축 보정) 재작업 시도: 경이 확인 요청(4인 회의로 돌리면 `policy_fit`·`budget_execution`에 배정된 채점 항목이 없음) 반영해 `rubric_mapping_government_support.json`을 2인(영상 MVP 공통 위원) 기준 → 4인 채점 위원 기준으로 재배정하고 PR #26로 올림
    - `policy_alignment`: `business_strategy` → `policy_fit`
    - `execution_plan`: 주담당 `technical_feasibility` → `budget_execution` (technical_feasibility는 보조로 유지)
  - → 경이 쪽에서 이 criterion-위원 매핑을 LangGraph에서 직접 동적으로 생성할 것 같아 PR #26 close, 커밋 `git revert`로 롤백 (`rubric_mapping_government_support.json`은 2인 버전으로 원복)
  - `frontend/README.md` 추가 (로컬 실행 방법, 팀 공유용)
  - (Claude Code와 세션) `manual_url_check.py` 실행 중 `ai/rag/parsers/{pdf,docx,pptx}_parser.py`
    3곳 모두 `DocumentExtractionResult` import 누락 발견·수정 (모듈 로드 시 NameError)
  - (Claude Code와 세션) `dev`를 `feature/pge`에 머지해 경이의 M4(LangGraph 노드 조립,
    `ai/meeting/graph/{build,nodes,evidence,llm,transform,rubric}.py`) 반영
  - (Claude Code와 세션) 공모전 도메인 우선순위 확정에 맞춰 A) `rubric_mapping_competition.json`을
    특정 공모전 하나가 아니라 재사용 가능한 기본 템플릿으로 승격(`reusable_as_default_template`
    메타 추가) B) `competition.json`의 `meeting_culture`에 "business_strategy가
    not_applicable을 내는 건 순수 기술/아이디어형 공모전에서 정상"이라는 위원장 개입
    지침 보강. government_support/startup은 보류
  - (Claude Code와 세션) MTG-007(특정 위원 재평가) 신규 구현 — `ai/meeting/graph/reevaluate.py`
    (`assemble_reevaluation_graph`/`reevaluation_state`, 경이 합의). evidence는
    `operator.add` 리듀서라 재평가 대상 위원의 예전 근거를 먼저 걷어내지 않으면
    evidence_id가 중복되는 문제를 발견해 `reevaluation_state()`에서 필터링
  - (Claude Code와 세션) **"다 이어버리자" — 전체 파이프라인 실연결**(RAG 색인 ->
    rubric/committee 구성 -> LangGraph -> 실제 OpenAI -> MongoDB 저장 -> 재평가)을
    실제 MongoDB/Chroma/OpenAI로 엔드투엔드 검증까지 완료:
    - `DocumentModel`에 `document_role`("target"=평가 대상 문서/기획서 |
      "criteria"=공고문)과 `parsed_text`(파싱 원문 전체) 필드 추가 — 이게 없으면
      analyze()가 어떤 문서를 채점 대상으로 쓸지, submission 텍스트를 어디서
      가져올지 방법이 없었음
    - `documents.py`의 `fetch_url()`이 정제까지만 하고 멈추던 걸 파일 업로드와
      동일하게 청킹/임베딩/Chroma 색인까지 연결(`_chunk_and_index_webpage`) —
      `chunk_document()`가 원래 `CleanedWebContent`도 받도록 설계돼 있어 새 파서는
      필요 없었음
    - `MeetingModel`/`MeetingRepository` 신설(MTG-005). committee/submission/
      retrieved_evidence를 review_output v2 문서 필드와 함께 저장해 재평가 시
      재구성이 필요 없게 함
    - `meetings.py`의 `analyze_project()`를 fixture 반환에서 실제 계산으로 교체:
      프로젝트 doc_type -> rubric_mapping_{domain}.json 로드, target 문서
      parsed_text로 submission 구성, rubric 기준별 `RAGIndexingService.search()`로
      retrieved_evidence 수집, `assemble_meeting_graph` + 실제 OpenAI 호출.
      `reevaluate_reviewer()`도 캔드 스텁 대신 실제 OpenAI 호출로 교체
    - LLM 호출 안전장치: `LLM_PROFILE=dev|quality` 프로필 분리(backend/.env),
      호출 상한, `recursion_limit`, 호출 로그 — 실제 LLM 붙는 코드마다 적용하기로
      한 규칙
    - `documentApi.js`/`DocumentUploadPage.jsx`가 `document_role`/`project_id`를
      백엔드에 넘기도록 수정 (왼쪽 드롭존=target, 오른쪽=criteria)
    - `MeetingChat.jsx`/`meetingTheme.js` 신규 — 위원 발언을 채팅 버블로 보여주는
      회의록 UI, `ProjectDetailPage.jsx`에 연결(dataviz 스킬로 팔레트 검증)
    - **실제 버그 발견·수정**: OpenAI가 reviewer raw JSON의 `persona_id`를 실제
      committee ID 대신 지어낸 값(`P-STRAT-01`, `TECH-EVAL-01` 등)으로 반환하는 걸
      실제 호출로 확인. LangGraph state의 딕셔너리 키(신뢰 가능)는 맞는데 리스트로
      펼치면서 LLM의 내부 필드를 썼던 게 원인 — `_reviewer_results_to_list()`로
      항상 딕셔너리 키를 덮어쓰게 방어 처리. 근본 원인(reviewer_prompt.txt/
      transform.py가 persona_id를 강제 안 함)은 경이 확인 필요로 남김
    - `backend/.env`가 루트 `.env`와 별도 파일로 존재하고 예전 `MONGODB_URL`
      (sherpa_admin, 다른 프로젝트 잔재)이 그대로 남아있던 걸 발견 — 루트 `.env`와
      같은 값(reviewboard_admin)으로 맞춤
  - (Claude Code와 세션) 실제 브라우저(로그인 -> 업로드 -> 분석)로 직접 확인하는 과정에서
    발견·수정한 것들:
    - `graph.invoke()`가 동기 함수인데 그냥 호출해서, 실제 OpenAI 호출이 도는 수십초~분
      동안 asyncio 이벤트 루프 전체가 막혀 서버가 로그인 같은 사소한 요청도 못 받는
      상태가 됨(health check조차 무응답). `documents.py`의 `_parse_chunk_and_index()`와
      동일하게 `run_in_threadpool()`로 감싸 해결 — 백그라운드 처리(polling/SSE) 여부와
      별개로, 지금 동기 구조를 유지하더라도 반드시 필요했던 수정
    - `frontend/.env.local`이 `VITE_API_BASE_URL=http://localhost:8001`로 설정돼 있어서
      프론트가 계속 (오늘 코드 변경 전의) 다른 백엔드 프로세스를 보고 있었음 — 그래서
      백엔드를 아무리 고쳐도 브라우저에서는 옛날 고정 fixture만 보였다. 8000으로 수정.
      로컬에 여러 uvicorn/vite 프로세스(다른 세션의 `persistent_tunnel.py` 포함)가 동시에
      떠 있어서 원인 파악이 오래 걸림 — 로컬 프로세스인지 확인 후 정리
  - (Claude Code와 세션) "비회원 로그인" 버튼이 UI만 있고 실제로는 아무 세션도 안 만들어서
    (그냥 `/projects`로 navigate만 함) 비회원으로는 프로젝트 생성부터 막혀 있던 걸 발견.
    처음엔 `/auth/guest`에서 매번 새 게스트 JWT를 발급하는 방식으로 고쳤다가, "인증 자체를
    아예 안 거치게 해달라"는 요청을 받고 다시 설계 변경: `projects.py`/`documents.py`/
    `meetings.py` 세 곳의 `get_current_user()`가 Authorization 헤더가 없으면 401 대신
    고정 게스트(`guest@local`)로 통과시키도록 수정. `/auth/guest` 엔드포인트와 프론트
    `guestLogin()`은 다시 제거 — 비회원 버튼은 이제 `localStorage`도 안 건드리고 그냥
    `/projects`로 이동만 한다. `test_documents.py`의 "인증 헤더 없으면 거부" 테스트도
    새 의도(게스트 허용)에 맞게 재작성
  - (Claude Code와 세션) 팀원A의 MongoDB 접속 실패(`Authentication failed, code 18`) 디버깅 지원 —
    SSH 터널 스크린샷/에러 메시지로 "터널·네트워크는 정상, 자격증명(.env) 쪽 문제"로 진단하고
    확인 절차 안내(코드 변경 없음)
  - (Claude Code와 세션) 로컬 백엔드 기동 실패(`ModuleNotFoundError: No module named 'openai'`)
    해결 — `review-board` conda 환경에 `openai` 패키지 설치.
    **`backend/local.requirements.txt`에 `openai` 추가 — 윤한 영역 파일, 확인 필요**
  - (Claude Code와 세션) `ProjectDetailPage.jsx`에 회의 결과 **".json 다운로드" 버튼** 추가 —
    현재 화면에 뜬 `result`(= `/analyze` 원본 응답, evidence 등 화면에 안 보이는 필드까지 포함)를
    `{meeting_id}.json`으로 클라이언트에서 바로 다운로드 (가은 영역, 백엔드 호출 없음)

- 결정/이유:
  - 정적 mock으로 매핑을 미리 확정해두기보다, 실제 매핑 로직은 경이의 LangGraph 구현(MTG-001~003) 쪽 판단을 따르기로 함 — 중복 산출물 방지
  - analyze()의 rubric/committee 소스로 공고문 자동 추출 대신 `rubric_mapping_{domain}.json` 정적 템플릿을 채택 — 용준의 공고문 평가기준 자동 추출 기능이 아직 없어서, 있는 조각으로 먼저 파이프라인을 실제로 완주시키는 걸 우선함
  - retrieved_evidence는 위원별로 나누지 않고(ai/rag/role_retrieval 미사용) committee 전체에 같은 검색 결과를 그대로 넘김 — 경이의 M4 그래프/프롬프트가 애초에 "위원 전체가 rubric 전체를 보고 본인 전문 범위만 검토"하도록 설계돼 있어(reviewer_prompt.txt) 지금 구조를 그대로 따름
  - 비회원은 매 세션 다른 `guest@local` 하나만 공유(요청/브라우저별로 구분 안 함) — 다른 비회원끼리 프로젝트 목록이 섞일 수 있음을 감수하고 단순하게 감. 실사용 전엔 재검토 필요

- 막힌 점 / 협의 필요:
  - `rubric_mapping_startup.json`이 없어서 startup 도메인 프로젝트는 analyze() 호출 시 400으로 막힘 (competition 우선순위 확정 이후 보류 중이라 당장 급하진 않음)
  - submission이 여러 개의 target 문서를 어떻게 합칠지 정해진 바 없음 — 지금은 첫 번째 target 문서만 사용
  - 위원별로 다른 retrieved_evidence를 주려면(역할 기반 검색) 경이의 그래프/프롬프트 구조 변경이 필요 — 지금은 손 안 댐
  - 응답 시간: committee 인원만큼 실제 OpenAI 호출이 걸려 수십 초~분 단위 소요(실측 3~4분/5회 호출). 지금은 동기 HTTP POST라 그대로 프론트가 기다림 — 백그라운드 처리(polling/SSE)로 바꿀지는 인프라(INF-007) 차원에서 윤한과 결정 필요
  - `backend/.env`와 루트 `.env`가 별도 파일로 계속 존재 — 하나로 합칠지 결정 필요
  - OpenAI가 reviewer raw JSON의 `persona_id`를 신뢰할 수 없게 반환하는 문제 — 지금은 백엔드(`meetings.py`)에서 방어적으로 덮어써서 우회했지만, 근본적으로는 `reviewer_prompt.txt`/`transform.py`(경이 담당)에서 persona_id를 강제하는 게 더 안전할 수 있음

- 다음 할 일:
  - 경이와 rubric-위원 매핑을 어느 쪽에서 관리할지(정적 mock vs 런타임 생성) 다시 정렬
  - PER-004(Persona Card 버전 관리 정책) 착수
  - 경이에게 `docs/prompts/*` 넘기고 `ai/meeting/prompts/{prompt_loader.py,reviewer_prompt.txt,chair_prompt.txt}` 변환 요청
  - `rubric_mapping_startup.json` 작성 여부 결정 (경이/가은)
  - persona_id 신뢰성 문제 근본 수정 여부 논의 (경이)
  - analyze() 응답시간 개선(백그라운드 처리) 설계 논의 (윤한)
  - `backend/.env` 통합 여부 결정 (윤한)
  - 프론트에 위원별 "재평가" 버튼을 `MeetingChat.jsx`에 연결 (백엔드 라우트는 준비됨)

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
