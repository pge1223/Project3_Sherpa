## 2026-07-14

- 한 일:
  - 프로젝트명 "Sherpa" → "ReviewBoard" 전체 리네이밍 완료
    - NCP 서버 systemd 서비스 파일명 및 설명 변경 (sherpa.service → review-board.service)
    - 로컬 프로젝트 폴더명 변경 (Project3_Sherpa → Project3_AIReviewBoard)
    - conda 환경 재생성 (sherpa → review-board)
  - USR-001 사용자 인증 API 구현 및 NCP 서버 배포
    - 회원가입/로그인 (bcrypt 비밀번호 암호화 + JWT 토큰 발급)
    - models/user.py, schemas/user.py, repositories/user_repository.py, api/routes/auth.py
    - JWT 환경변수 분리, email-validator 추가
    - systemd 자동 재시작 설정 완료
  - PRJ-001~004 프로젝트 CRUD API 구현 및 배포
    - models/project.py, schemas/project.py, repositories/project_repository.py, api/routes/projects.py
    - main.py에 project_router 등록
    - Swagger(/docs)에서 동작 확인
  - MongoDB SSH 터널링 설정 (NCP → 홈서버 220.81.7.136)
    - MongoDB 인증 활성화, 외부 포트 차단, SSH 터널링 전환
  - dev 브랜치 충돌 해결 후 PR #22 제출
  - 포트 충돌 발생 → fuser -k 8000/tcp로 해결 후 서비스 재시작

- 결정/이유:
  - MongoDB 외부 포트 차단 후 SSH 터널로만 접근하도록 변경
    → 랜섬웨어 피해 재발 방지 목적
  - systemd 서비스 파일 편집 시 nano 대신 heredoc(cat > file << 'EOF') 방식 사용
    → nano 오타 실수 반복으로 인한 서비스 장애 예방
  - 기존 코드베이스 패턴 그대로 유지 (순수 Python 모델 + to_dict(), async repository)
    → 팀원 코드와 충돌 최소화

- 막힌 점:
  - dev 브랜치 머지 충돌 발생 → fetch 후 수동 해결
  - 포트 8000 충돌 → fuser -k 8000/tcp로 해결

- 다음 할 일:
  - DOC-001~002: 문서 업로드 API
  - MTG-005: 회의 기록 저장
  - INF-003~007: 파일 저장, 보안, 로깅