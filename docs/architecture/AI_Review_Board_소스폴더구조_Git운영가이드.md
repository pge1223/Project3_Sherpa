# AI Review Board 소스 폴더 구조 및 Git 운영 가이드

## 1. 권장 저장소 구조

AI Review Board는 프론트엔드, 백엔드, RAG, LangGraph, AI 영상 모듈을 하나의 Git 저장소에서 관리하는 **모노레포 구조**를 권장한다.

각 담당자는 자신의 작업 폴더에서 병렬 개발하고, 공통 JSON 규격은 `contracts/`에서 함께 관리한다.

```text
ai-review-board/
│
├─ README.md
├─ .gitignore
├─ .env.example
├─ docker-compose.yml
│
├─ docs/
│  ├─ requirements/
│  │  ├─ 요구사항정의서.xlsx
│  │  └─ 병렬개발_업무흐름.md
│  │
│  ├─ architecture/
│  │  ├─ system_architecture.md
│  │  ├─ api_flow.md
│  │  └─ meeting_flow.md
│  │
│  └─ prompts/
│     ├─ persona_spec.md
│     ├─ reviewer_prompt.md
│     └─ chair_prompt.md
│
├─ contracts/
│  ├─ meeting_contract_v1.json
│  │
│  ├─ schemas/
│  │  ├─ project.schema.json
│  │  ├─ document.schema.json
│  │  ├─ rag_response.schema.json
│  │  ├─ reviewer_result.schema.json
│  │  ├─ meeting_result.schema.json
│  │  └─ media_script.schema.json
│  │
│  └─ mocks/
│     ├─ project.json
│     ├─ document_status.json
│     ├─ rag_response.json
│     ├─ reviewer_result.json
│     ├─ final_meeting_result.json
│     ├─ media_script.json
│     └─ media_job_result.json
│
├─ frontend/
│  ├─ package.json
│  ├─ vite.config.js
│  ├─ public/
│  │  ├─ images/
│  │  └─ mock-videos/
│  │
│  └─ src/
│     ├─ api/
│     │  ├─ client.js
│     │  ├─ projectApi.js
│     │  ├─ documentApi.js
│     │  ├─ meetingApi.js
│     │  └─ reportApi.js
│     │
│     ├─ components/
│     │  ├─ common/
│     │  ├─ upload/
│     │  ├─ meeting/
│     │  └─ report/
│     │
│     ├─ pages/
│     │  ├─ LoginPage.jsx
│     │  ├─ ProjectListPage.jsx
│     │  ├─ ProjectDetailPage.jsx
│     │  ├─ DocumentUploadPage.jsx
│     │  ├─ MeetingPage.jsx
│     │  └─ ReportPage.jsx
│     │
│     ├─ mocks/
│     ├─ hooks/
│     ├─ stores/
│     ├─ utils/
│     ├─ App.jsx
│     └─ main.jsx
│
├─ backend/
│  ├─ requirements.txt
│  ├─ Dockerfile
│  │
│  ├─ app/
│  │  ├─ main.py
│  │  ├─ config.py
│  │  │
│  │  ├─ api/
│  │  │  ├─ dependencies.py
│  │  │  └─ routes/
│  │  │     ├─ auth.py
│  │  │     ├─ projects.py
│  │  │     ├─ documents.py
│  │  │     ├─ meetings.py
│  │  │     ├─ reports.py
│  │  │     └─ media.py
│  │  │
│  │  ├─ models/
│  │  │  ├─ user.py
│  │  │  ├─ project.py
│  │  │  ├─ document.py
│  │  │  ├─ meeting.py
│  │  │  └─ evaluation.py
│  │  │
│  │  ├─ schemas/
│  │  │  ├─ project.py
│  │  │  ├─ document.py
│  │  │  ├─ meeting.py
│  │  │  └─ report.py
│  │  │
│  │  ├─ repositories/
│  │  │  ├─ project_repository.py
│  │  │  ├─ document_repository.py
│  │  │  └─ meeting_repository.py
│  │  │
│  │  ├─ services/
│  │  │  ├─ project_service.py
│  │  │  ├─ document_service.py
│  │  │  ├─ meeting_service.py
│  │  │  ├─ media_service.py
│  │  │  └─ storage_service.py
│  │  │
│  │  ├─ db/
│  │  │  ├─ mongodb.py
│  │  │  └─ indexes.py
│  │  │
│  │  └─ common/
│  │     ├─ exceptions.py
│  │     ├─ response.py
│  │     └─ constants.py
│  │
│  └─ tests/
│
├─ ai/
│  ├─ rag/
│  │  ├─ parsers/
│  │  │  ├─ pdf_parser.py
│  │  │  ├─ docx_parser.py
│  │  │  └─ pptx_parser.py
│  │  │
│  │  ├─ chunking/
│  │  │  ├─ chunker.py
│  │  │  └─ metadata.py
│  │  │
│  │  ├─ embedding/
│  │  │  ├─ embedding_model.py
│  │  │  └─ vector_store.py
│  │  │
│  │  ├─ retrieval/
│  │  │  ├─ retriever.py
│  │  │  ├─ query_builder.py
│  │  │  └─ filters.py
│  │  │
│  │  ├─ domain/
│  │  │  ├─ classifier.py
│  │  │  └─ criteria_extractor.py
│  │  │
│  │  ├─ evaluation/
│  │  │  └─ rag_evaluator.py
│  │  │
│  │  └─ tests/
│  │
│  ├─ meeting/
│  │  ├─ graph/
│  │  │  ├─ state.py
│  │  │  ├─ builder.py
│  │  │  ├─ edges.py
│  │  │  └─ nodes/
│  │  │     ├─ prepare_context.py
│  │  │     ├─ reviewer_a.py
│  │  │     ├─ reviewer_b.py
│  │  │     ├─ score_calculation.py
│  │  │     ├─ chair_summary.py
│  │  │     └─ media_script.py
│  │  │
│  │  ├─ prompts/
│  │  │  ├─ prompt_loader.py
│  │  │  ├─ reviewer_prompt.txt
│  │  │  └─ chair_prompt.txt
│  │  │
│  │  ├─ personas/
│  │  │  ├─ startup.json
│  │  │  ├─ government.json
│  │  │  └─ contest.json
│  │  │
│  │  ├─ scoring/
│  │  │  ├─ calculator.py
│  │  │  ├─ deductions.py
│  │  │  └─ weights.py
│  │  │
│  │  └─ tests/
│  │
│  └─ media/
│     ├─ tts/
│     │  ├─ tts_client.py
│     │  └─ voice_map.json
│     │
│     ├─ musetalk/
│     │  ├─ generate_video.py
│     │  └─ colab/
│     │     └─ musetalk_demo.ipynb
│     │
│     ├─ assets/
│     │  ├─ persona_a/
│     │  └─ persona_b/
│     │
│     ├─ fallback/
│     │  └─ fallback_generator.py
│     │
│     └─ tests/
│
├─ scripts/
│  ├─ init_db.py
│  ├─ seed_mock_data.py
│  ├─ ingest_documents.py
│  └─ run_evaluation.py
│
└─ tests/
   ├─ integration/
   └─ fixtures/
```

---

## 2. 담당자별 작업 폴더

| 담당자 | 주요 작업 폴더 |
|---|---|
| 가은 | `frontend/`, `docs/prompts/`, `contracts/mocks/` |
| 윤한 | `backend/`, `scripts/`, 배포 설정 |
| 경이 | `ai/meeting/`, `contracts/schemas/` |
| 용준 | `ai/rag/` |
| 재인 | `ai/media/` |

`contracts/`는 공통 계약 폴더이므로 특정 한 명의 개인 작업 폴더로 보기보다, 변경 시 Pull Request 리뷰를 받는 방식으로 관리한다.

---

## 3. 프롬프트 파일 구분

### 3.1 기획용 프롬프트

가은이 작성하는 사람이 읽는 기획 문서다.

```text
docs/prompts/
├─ persona_spec.md
├─ reviewer_prompt.md
└─ chair_prompt.md
```

포함 내용:

- Persona Card
- 평가 관점
- 말투와 태도
- 회의 순서
- 근거 사용 규칙
- 위원별 프롬프트 초안
- 위원장 프롬프트 초안

### 3.2 실행용 프롬프트

경이가 LangGraph에서 실제로 불러오는 실행 파일이다.

```text
ai/meeting/prompts/
├─ prompt_loader.py
├─ reviewer_prompt.txt
└─ chair_prompt.txt
```

작업 흐름:

```text
가은 기획 초안
docs/prompts/
        ↓
경이 실행용 프롬프트 변환
ai/meeting/prompts/
        ↓
LangGraph 노드에서 호출
```

---

## 4. 공통 계약 폴더

```text
contracts/
├─ meeting_contract_v1.json
├─ schemas/
└─ mocks/
```

### `meeting_contract_v1.json`

회의 규칙, 입출력 구조, 점수 계산 규칙, 영상 스크립트 구조를 정의한다.

### `schemas/`

각 데이터가 올바른 구조인지 검증하기 위한 JSON Schema를 보관한다.

### `mocks/`

실제 모듈이 완성되기 전 병렬 개발에 사용하는 샘플 데이터를 보관한다.

```text
contracts/mocks/
├─ project.json
├─ document_status.json
├─ rag_response.json
├─ reviewer_result.json
├─ final_meeting_result.json
├─ media_script.json
└─ media_job_result.json
```

공통 스키마 변경 시에는 관련 Mock 파일도 함께 수정한다.

---

## 5. Git에 올리면 안 되는 파일

아래 파일은 저장소에 올리지 않는다.

- 실제 API Key
- `.env`
- 사용자 업로드 문서
- 실제 사업계획서·공고문 원본
- Chroma 벡터DB 데이터
- MongoDB 로컬 데이터
- 대용량 모델 파일
- 생성된 음성과 영상
- 로그 파일
- 가상환경 및 패키지 설치 폴더

권장 `.gitignore`:

```gitignore
# 환경변수
.env
.env.*
!.env.example

# Python
__pycache__/
*.py[cod]
.venv/
venv/
.pytest_cache/
.mypy_cache/

# Node
node_modules/
dist/
.vite/

# IDE
.vscode/
.idea/

# OS
.DS_Store
Thumbs.db

# 로그
logs/
*.log

# 업로드 문서
uploads/
storage/
temp/
tmp/

# Vector DB
chroma_db/
vector_store/

# MongoDB 데이터
mongodb_data/

# 모델 및 대용량 파일
models/
checkpoints/
*.ckpt
*.pth
*.pt
*.onnx
*.safetensors

# 생성된 음성·영상
generated/
outputs/
*.mp3
*.wav
*.mp4
*.avi

# 사용자 제출 자료
data/private/
data/uploads/
```

AI 영상과 모델 파일은 GitHub에 직접 올리지 않고 NCP Object Storage, Google Drive 등 외부 저장소에 보관한다.

저장소에는 실제 파일 대신 아래 정보만 기록한다.

```json
{
  "persona_id": "business_strategy",
  "video_url": "NCP Object Storage URL",
  "voice_id": "voice_a"
}
```

---

## 6. 환경변수 관리

실제 키는 `.env`에 작성하고 Git에 올리지 않는다.

```env
MONGODB_URL=mongodb://localhost:27017
MONGODB_DB=ai_review_board

OPENAI_API_KEY=
GOOGLE_API_KEY=

NCP_ACCESS_KEY=
NCP_SECRET_KEY=
NCP_BUCKET_NAME=

CHROMA_PERSIST_DIR=./chroma_db
```

팀 공유용으로는 값이 비어 있는 `.env.example`만 올린다.

```bash
cp .env.example .env
```

각 팀원은 로컬에서 `.env`를 별도로 작성한다.
