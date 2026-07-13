# AI Review Board — 프로젝트 컨텍스트

> 이 파일은 레포 루트에 위치하며, Claude Code가 어떤 하위 폴더에서 실행되든
> 자동으로 읽어들이는 "전역 컨텍스트"입니다.

## 프로젝트 한 줄 요약
문서를 평가하는 AI가 아니라, 문서를 놓고 전문가들이 회의하는 AI 위원회.
사업계획서·공모전 기획서·IR 덱 등을 업로드하면 관련 공고문·평가기준을
RAG로 수집해 그에 맞는 전문가 페르소나(위원)를 자동 구성하고, 각 위원이
독립적으로 검토한 뒤 위원장이 종합해 회의록 형태로 피드백을 돌려준다.

> 참고: 이 레포는 이전에 "지원금 셰르파"(정부 지원사업 매칭 앱)로
> 시작했으나 폐기되었다. 관련 문서나 코드가 남아 있어도 현재 프로젝트와
> 무관하므로 되살리거나 참고하지 말 것.

## 팀 & 역할 (최종 역할 분담)
| 이름 | 담당 영역 | 핵심 결과물 |
|---|---|---|
| 가은 | PM, React 프론트, 페르소나·프롬프트 기획 | 화면 흐름, Persona Card, 프롬프트 초안, React UI |
| 윤한 | FastAPI, MongoDB, CRUD, NCP | API, DB 스키마, 파일·영상 저장, 배포 환경 |
| 경이 | LangGraph, 점수 엔진, 평가 결과 구조 | 회의 워크플로, 평가 결과 JSON, 점수 계산 |
| 용준 | RAG 파이프라인 | 문서 파싱, 청킹, 임베딩, 검색, 출처 연결 |
| 재인 | AI 휴먼 영상 제작 | 페르소나 영상 2종, TTS, MuseTalk, 영상 폴백 |

담당 외 영역(특히 `contracts/`, `docs/architecture/`, `.env.example`,
`docker-compose.yml`, `README.md` 등 공통 파일) 수정 시 반드시 해당
담당자와 상의할 것.

## 아키텍처 — 회의 진행 순서
1. **문서 업로드** — 검토받을 사업계획서·기획서·IR 덱 등
2. **공고문·평가기준 RAG 수집** — 해당 공모전/사업의 심사 기준을 검색해 문서 성격 파악
3. **위원회 구성** — 문서 종류에 따라 필요한 역량을 추출해 위원 페르소나 매칭 (도메인마다 참석자·회의 문화가 다름)
4. **1차 회의 — 개별 리뷰** — 각 위원이 서로의 발언을 보지 않고 독립적으로 검토
5. **2차 회의 — 위원장 종합** — 1차 의견을 종합해 쟁점 정리 및 액션 아이템 제시
6. **회의록 반환·반복 검토** — 회의록 기반 수정 후 재검토 가능

핵심 차별점: RAG는 답변이 아니라 **위원 페르소나를 만드는 재료**로 쓰이며,
평가 점수가 아니라 **회의(각자 근거를 든 발언 + 위원장 종합)** 형태로
결과를 돌려준다.

## 기술 스택
| 영역 | 기술 | 역할 |
|---|---|---|
| Frontend | React + Vite | 회의실 UI, 위원별 발언 화면 |
| Backend | FastAPI | RAG·에이전트 파이프라인과 프론트를 연결하는 API 서버 |
| RAG | LangChain · KURE-v1 · Chroma (Persistent) | 공고문·평가기준 수집/임베딩/검색, 페르소나 생성 기반 자료 |
| Workflow | LangGraph | 위원별 독립 리뷰(1차) → 위원장 종합(2차) 오케스트레이션 |
| LLM | OpenAI / Anthropic API | 역할별로 경량·고성능 모델 분리 사용 |
| Document Parsing | PyMuPDF · python-docx · python-pptx | PDF/워드/PPT 파싱 |
| Database | MongoDB | 사용자 문서, 회의 기록, 위원 평점 저장 |
| Infra / Hosting | NCP (Naver Cloud Platform) | 서버 호스팅 및 배포 |
| Human AI | TTS + LivePortrait / Wav2Lip / MuseTalk (Colab GPU) | 위원 발언 영상화 |
| Monitoring | LangSmith / 자체 로그 | 프롬프트·검색 품질, 근거 인용 정확도 추적 |

## 개발 방식 — 공통 계약 우선 (Mock 기반 병렬 개발)
각 담당자는 다른 담당자의 완성본을 기다리지 않고, **미리 정의된 JSON
계약과 Mock 데이터**를 기준으로 동시에 개발한다.

- 공통 계약 기준 파일: `contracts/meeting_contract_v1.json`
- Mock 데이터: `contracts/mocks/*.json`
- 필드 삭제·이름 변경은 피하고, 필요하면 새 선택 필드를 추가한다
  (버전 규칙: v1.0.0 최초 확정 → v1.1.0 선택 필드 추가 → v2.0.0 구조 변경)
- 공통 JSON 구조 변경 시: 변경 제안 → 영향받는 담당자 확인 → 팀 동의 →
  schema_version 변경 → Mock 파일 갱신 → 코드 반영

## 프롬프트 파일 구분
- **기획용** (`docs/prompts/`): 가은이 작성하는, 사람이 읽는 기획 문서
  (Persona Card, 평가 관점, 말투, 회의 순서, 근거 사용 규칙)
- **실행용** (`ai/meeting/prompts/`): 경이가 LangGraph에서 실제로 불러오는
  실행 파일 (`prompt_loader.py`, `reviewer_prompt.txt`, `chair_prompt.txt`)
- 흐름: 가은 기획 초안 → 경이가 실행용 프롬프트로 변환 → LangGraph 노드에서 호출

## 소스 폴더 구조
모노레포 구조. 최상위: `frontend/`, `backend/`, `ai/{rag,meeting,media}/`,
`contracts/{schemas,mocks}/`, `docs/{requirements,architecture,prompts}/`,
`scripts/`, `tests/`. 상세 트리는 `AI_Review_Board_소스폴더구조_Git운영가이드.md` 참고.

## Git에 올리면 안 되는 파일
실제 API Key, `.env`, 사용자 업로드 문서, 실제 사업계획서·공고문 원본,
Chroma 벡터DB 데이터, MongoDB 로컬 데이터, 대용량 모델 파일, 생성된
음성·영상, 로그 파일, 가상환경/패키지 설치 폴더. 규칙은 레포 루트
`.gitignore`에 반영되어 있다.

- `ai/**/models/` 하위(대용량 모델 파일)만 무시하며, `backend/app/models/`
  (DB 모델 코드 폴더)는 예외로 추적 대상이다 — 이 둘을 혼동해 규칙을
  되돌리지 말 것
- AI 영상·모델 파일은 GitHub에 올리지 않고 NCP Object Storage 등 외부
  저장소에 보관, 레포에는 URL만 기록
- `pge_doc/`은 팀원 개인 스크래치/기획 문서 폴더로 항상 gitignore 대상

## 환경변수 관리
실제 키는 로컬 `.env`에 작성하고 Git에 올리지 않는다. 팀 공유용으로는
값이 비어 있는 `.env.example`만 커밋한다 (`cp .env.example .env`로 로컬
설정). 주요 키: `MONGODB_URL`, `MONGODB_DB`, `OPENAI_API_KEY`,
`GOOGLE_API_KEY`, `NCP_ACCESS_KEY`, `NCP_SECRET_KEY`, `NCP_BUCKET_NAME`,
`CHROMA_PERSIST_DIR`.

## 브랜치 운영
`main`(배포/시연 가능한 안정 버전)과 `dev`만 사용한다. `develop`이나
`feature/*` 같은 별도 브랜치를 새로 만들지 않는다 (팀 확정 사항). `main`은
GitHub 브랜치 보호 규칙이 걸려 있을 수 있으니, 보호 규칙 변경이 필요하면
반드시 먼저 확인받을 것.

## Claude Code에게: 이 프로젝트에서 지켜야 할 것
- "지원금 셰르파" 관련 문서/코드가 눈에 띄어도 현재 프로젝트와 무관하니
  참고하거나 되살리지 말 것
- 공통 계약 파일(`contracts/`)이나 `docs/architecture/` 등 공용 파일을
  수정할 때는 어느 담당자 영역인지 먼저 확인하고 언급할 것
- `.gitignore`의 `ai/**/models/` 규칙과 `backend/app/models/` 코드 폴더를
  혼동하지 말 것
- `main`/`dev` 외 새 브랜치(특히 `develop`)를 임의로 만들지 말 것
