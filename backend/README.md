# Backend 로컬 실행 방법

## 사전 준비

레포 루트에서 conda 환경을 만든다 (Python 3.11).

```bash
conda env create -f environment.yml
conda activate review-board
pip install -r requirements.txt
```

## 환경변수

`backend/.env` 파일이 별도로 필요하다 (레포 루트 `.env`와 다른 파일). `Settings` 클래스가 선언되지 않은 필드를 만나면 기동에 실패하므로, 아래 필드만 채운다.

```env
MONGODB_URL=mongodb://localhost:27017
MONGODB_DB=ai_review_board

OPENAI_API_KEY=

NCP_ACCESS_KEY=
NCP_SECRET_KEY=
NCP_BUCKET_NAME=
```

`MONGODB_URL`은 실제 접속 가능한 MongoDB가 필요하다. 아직 `ai_review_board`용 정식 DB가 없어서, 현재는 SSH 터널로 임시 서버에 연결해 쓰고 있다. 접속 정보는 팀(윤한 또는 pge)에게 문의.

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
| `/health` | GET | 헬스 체크 |
| `/auth/register` | POST | 회원가입 |
| `/auth/login` | POST | 로그인 (JWT 발급) |
