# Backend 로컬 실행 방법

## 사전 준비

레포 루트에서 conda 환경을 만든다 (Python 3.11).

```bash
conda env create -f environment.yml
conda activate review-board
pip install -r requirements.txt
```

## 환경변수

`backend/.env` 파일이 별도로 필요하다 (레포 루트 `.env`와 다른 파일 — 역할이 다르다).
`cp backend/.env.example backend/.env`로 시작해 값을 채운다. `Settings` 클래스가
선언되지 않은 필드를 만나면 기동에 실패하므로, `backend/.env.example`에 있는 필드만 채운다.

- **레포 루트 `.env`** (`.env.example`이 템플릿): `scripts/`의 RAG 관련 스크립트, sherpa
  마이그레이션 스크립트 등이 읽는다. backend 프로세스는 이 파일을 직접 읽지 않는다.
- **`backend/.env`** (`backend/.env.example`이 템플릿): `backend/app/config.py`의
  `Settings`가 항상 이 경로(`backend/.env`)를 읽는다 — uvicorn 실행 위치(cwd)와 무관.
  MongoDB/OpenAI 키뿐 아니라 HWP 변환 설정(`HWP_*`)도 여기에 둔다.

`MONGODB_URL`은 실제 접속 가능한 MongoDB가 필요하다. 아직 `ai_review_board`용 정식 DB가 없어서, 현재는 SSH 터널로 임시 서버에 연결해 쓰고 있다. 접속 정보는 팀(윤한 또는 pge)에게 문의.

## HWP/HWPX 업로드 (LibreOffice 변환) 설정

문서 업로드에서 HWP/HWPX 파일은 `ai/rag/converters`가 LibreOffice headless로 PDF로
변환한 뒤 기존 PDF 파서로 처리한다 (`ai/rag/converters/hwp_pdf_converter.py`). 새 환경에서
처음 세팅할 때 아래를 준비해야 업로드 시 `HWP/HWPX 변환 도구(LibreOffice)를 찾을 수
없습니다` 오류가 나지 않는다.

1. **LibreOffice 설치** (Windows: `winget install --id TheDocumentFoundation.LibreOffice`,
   또는 https://www.libreoffice.org/download/download/ 에서 설치). winget/공식 인스톨러는
   설치해도 `soffice`를 PATH에 자동으로 추가하지 않는다.
2. **H2Orestart 확장 설치** — LibreOffice는 HWP/HWPX 가져오기 필터를 기본 내장하지
   않는다. https://github.com/ebandal/H2Orestart/releases 에서 최신 `.oxt`를 받아 설치한다.
   ```bash
   "C:\Program Files\LibreOffice\program\unopkg.exe" add H2Orestart.oxt
   ```
3. **Java 런타임** — H2Orestart는 Java 기반 확장이라 JRE가 필요하다 (`java -version`으로 확인).
4. **`HWP_CONVERTER_EXECUTABLE` 설정** — `backend/.env.example`이 템플릿이다.
   `cp backend/.env.example backend/.env`로 시작한다. **기본은 비워두는 것**을 권장한다:
   ```env
   HWP_CONVERSION_ENABLED=true
   HWP_CONVERTER_EXECUTABLE=
   ```
   값을 비워두면 PATH에서 `soffice`/`libreoffice`를 찾고, 그마저 없으면(Windows만)
   기본 설치 경로(`C:\Program Files\LibreOffice\program\soffice.exe`,
   `C:\Program Files (x86)\LibreOffice\program\soffice.exe`)를 마지막으로 확인한다 — 이
   폴백 순서는 OS를 가리지 않고 그대로 동작하므로, `.env.example`에 특정 OS 경로를
   활성값으로 박아두지 않는다(Linux 서버에 Windows 경로가 그대로 복사되면 실제 설치된
   `/usr/bin/soffice`를 두고도 "찾을 수 없음"으로 실패하기 때문).

   경로를 **명시적으로** 지정해야 한다면(예: PATH에 없는 위치에 설치했거나, 여러
   버전이 섞여 있어 특정 실행 파일을 고정하고 싶을 때):
   ```env
   # Windows
   HWP_CONVERTER_EXECUTABLE=C:\Program Files\LibreOffice\program\soffice.exe
   # Linux
   # HWP_CONVERTER_EXECUTABLE=/usr/bin/soffice
   ```
   **운영 서버**에서는 이 값을 `.env` 파일 대신 배포 파이프라인의 환경변수나 NCP
   secret/config 관리 기능으로 주입하는 것을 권장한다. 명시한 경로에 실제 실행
   파일이 없으면 **PATH로 조용히 폴백하지 않고** `unavailable`로 처리한다(관리자가
   지정한 값이 잘못됐다는 신호를 감추지 않기 위함) — `GET /health`의
   `capabilities.hwp_conversion.libreoffice=false`로 바로 드러난다.

   주의: `backend/app/config.py`의 `Settings`(pydantic-settings)는 `backend/.env`를 자체
   `Settings` 인스턴스로만 읽고 `os.environ`에는 반영하지 않는다. `ai/rag/converters/config.py`는
   이와 별개로, `os.environ`을 전역으로 건드리지 않으면서 `HWP_*` 6개 키만 다음 우선순위로
   읽는다: **실제 OS 환경변수 > `backend/.env` > 레포 루트 `.env` > 코드 기본값**
   (`python-dotenv`의 `dotenv_values()`로 파일을 읽기만 할 뿐 `os.environ`에는 쓰지 않는다 —
   MongoDB/OpenAI 키 등 HWP와 무관한 값은 아예 읽지도 않는다).

**설치/설정 확인 명령**

```bash
# LibreOffice 확장 등록 확인 (H2Orestart가 목록에 있어야 함)
"C:\Program Files\LibreOffice\program\unopkg.exe" list

# Java 확인
java -version

# 실제 변환 확인 (테스트 파일로 PDF가 생성되는지)
"C:\Program Files\LibreOffice\program\soffice.exe" --headless --convert-to pdf --outdir <출력폴더> <테스트파일.hwp>
```

**서버 시작 시 자동 점검** — `backend/app/main.py`의 startup 이벤트가
`ai/rag/converters/diagnostics.run_hwp_diagnostics()`를 한 번 실행해 위 4가지(LibreOffice,
Java, H2Orestart, 임시 디렉터리 쓰기 가능 여부)를 확인하고 결과를 로그로 남긴다
(`[HWP_CONVERTER_READY] ...` 또는 `[HWP_CONVERTER_UNAVAILABLE] reason=...`). 같은 결과는
`GET /health` 응답의 `capabilities.hwp_conversion`에서도 확인할 수 있다 — `enabled=true`인데
`available=false`면 서버 전체 `status`가 `"degraded"`로 표시된다(의도적으로
`HWP_CONVERSION_ENABLED=false`로 꺼둔 경우는 `"ok"`를 유지한다). 이 진단은 startup 시
1회만 실행되며 soffice/unopkg/java를 매 `/health` 요청마다 다시 실행하지 않는다.

**fail-safe 정책** — 진단 코드 자체에서 예상하지 못한 예외가 나도(예: 설정 파싱
오류, 권한 문제로 임시 디렉터리 접근 실패 등) 서버 기동은 계속되지만, 그 실패를
`enabled=false`(의도적 비활성화)로 위장해 `status="ok"`를 반환하지 않는다 — 알 수
없거나 실패한 상태는 항상 `enabled=true`/`available=false`로 처리해 `status="degraded"`가
뜨게 한다. 원본 예외 메시지나 절대 경로는 API 응답에 담기지 않고 서버 로그
(`[HWP_CONVERTER_DIAGNOSTICS_ERROR]`)에만 남는다.

## 실행

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

`http://localhost:8000/` 접속 시 `{"message": "AI Review Board API is running"}`이 나오면 정상.

## 현재 구현된 API

| 경로 | 메서드 | 설명 |
|---|---|---|
| `/` | GET | 헬스 체크 |
| `/health` | GET | 헬스 체크 (`capabilities.hwp_conversion`에 HWP 변환 가능 상태 포함) |
| `/auth/register` | POST | 회원가입 |
| `/auth/login` | POST | 로그인 (JWT 발급) |
