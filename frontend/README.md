# Frontend 로컬 실행 방법

## 사전 준비

- Node.js 18 이상 (권장: 20+)

## 설치 및 실행

```bash
cd frontend
npm install
npm run dev
```

`npm run dev` 실행 후 브라우저에서 http://localhost:5173/ 접속.

## 화면 구성

| 경로 | 화면 | 비고 |
|---|---|---|
| `/` | 랜딩 페이지 | 정적 UI, 백엔드 불필요 |
| `/login` | 로그인 | 실제 백엔드 `/auth/login` 호출 — 지금은 각자 테스트 안 해도 됨 (아래 참고) |
| `/projects` | 내 프로젝트 목록 | 현재 Mock 데이터 |
| `/projects/new` | 문서 업로드 | 파일 선택·드래그앤드롭 동작(클라이언트 시뮬레이션), Mock 데이터 |
| `/projects/:projectId` | 프로젝트 상세 | 플레이스홀더 |

## 로그인은 지금 각자 테스트하지 않아도 됨

로그인 화면(`/login`)은 실제 백엔드(FastAPI) + MongoDB 연결까지 다 갖춰져야 동작한다. 지금은 이 연결(백엔드 실행 + SSH 터널로 DB 연결)이 담당자(가은) 로컬 PC에서만 떠 있는 상태라, 각자 로컬에서 로그인 버튼을 눌러도 정상 동작하지 않는다.

**팀원들은 당장은 로그인은 건너뛰고, `/projects`·`/projects/new` 같은 Mock 데이터 화면 위주로 확인하면 된다.** 실제 로그인까지 각자 테스트하고 싶으면 백엔드 담당자(윤한)와 DB 연결 방법을 맞춘 뒤 진행한다.

그동안은 로그인 화면(`/login`)의 "로그인" 버튼 아래 "비회원 로그인" 버튼을 누르면 인증 없이 바로 `/projects`로 넘어간다 (임시 우회용, 나중에 제거 예정).

백엔드를 직접 띄우는 방법은 [`backend/README.md`](../backend/README.md) 참고. 백엔드를 `localhost:8000`이 아닌 다른 포트/주소로 띄웠다면 `frontend/.env`에 아래처럼 지정한다.

```env
VITE_API_BASE_URL=http://localhost:8000
```

## 빌드

```bash
npm run build
npm run preview
```
