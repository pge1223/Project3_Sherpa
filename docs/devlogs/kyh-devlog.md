### 7/21 — 스키마 fix + 다수 PR 배포

- **로컬 최신화 + NCP 배포 (오전)** — dev 머지 (민경이 LangGraph + 가은님 프론트 대거 반영)
- **경이님 분류기 계약 스펙 스키마 반영 작업**
  - `backend/app/schemas/user.py` 수정: `degree` Literal enum, `graduation_status` 신설, `experience` 필드명 변경(`internship_months`/`competition_count`/`award_count`), `github` 조회불가 필드 제거(`has_backend_experience`/`relevant_projects`/`total_commits`) → `public_repos`/`followers`/`total_stars` 신설
  - `ai/meeting/tests/fixtures/user_profile_samples.json` 갱신
  - PR #119 — Files changed 0으로 빈 PR 머지됨 (Claude Code 커밋 누락 버그)
  - PR #120 — 실제 파일 변경 재반영, 머지 완료 + NCP 배포
  - 경이님 `feature/mky` (#118) — `personalization.py` 새 필드명으로 가중치 로직 수정, 동시 머지
- **다수 PR 머지 + 배포**
  - PR #121~#123 머지 대응 NCP 배포 (워크벤치 라우트, PDF 미리보기, LangGraph transform 등 대규모 반영)
- **NCP 크레딧 20만원 재문의** — 7/16 문의(W20260716365374) 미처리로 재접수(W20260721366071)
- **트러블슈팅**: PR #119 빈 PR 문제 — Claude Code가 파일 수정 후 커밋에 미포함, 로컬 직접 확인 후 수동 커밋으로 해결

### 7/20 — 소통혁신24 IT 공모전 데이터 수집 완료

- AJAX 직접 호출 방식으로 소통혁신24 크롤링 (Selenium → requests 전환)
- `contest_announcements_it` — IT 공고 360건 저장 (241페이지 전수 스캔)
- `contest_works` — 수상작(winner) 468건 + 수상후보작(candidate) 486건 = 954건 저장
- IT 키워드 필터링, wrk_id 고유키 중복 방지, selection_status로 구분
- 이미지 URL + 수상등급 저장, OCR은 대표작 20~30건 검증 후 확대 예정
- 스크립트: `test_crawl.py`, `crawl_sotong_winners.py`
- PR #96 머지 + NCP 배포 완료

## 2026-07-18

### 작업 내용
- INF-007 fetch-url 색인 백그라운드화
  - asyncio.create_task()로 색인 백그라운드 이관
  - 즉시 응답 반환 (status="indexing")
  - 타임아웃 120초 → indexing_timeout 상태 저장
  - _index_webpage_background() 함수 추가
- ai/rag/loaders/schemas.py → 가은님 FetchUrlResponse 서브클래스 방식 채택
- dev 머지 후 NCP 서버 배포 완료

### 참고
- 충돌 해결: 가은님 폴링 작업과 documents.py 동일 파일 수정으로 충돌 발생 → 수동 해결
- 용준님 RAG 영역(schemas.py) additive 변경 확인 완료

[2026-07-17] AI Review Board 개발 일지

한 일:
- PRJ-004 프로젝트 cascade delete 구현
  (Chroma 벡터 청크 + MongoDB 문서/회의 동시 삭제)
- MeetingRepository.delete_by_id() 추가
- RAG-003~005 MeetingEvidenceOrchestrationService 연결
  (_search_evidence_for_rubric() → 오케스트레이션 서비스로 교체)
- DOC-006 문서 원문/추출문 미리보기 엔드포인트 추가
- RPT-005 평가 결과 PDF 내보내기 엔드포인트 추가 (reportlab)
- NCP 서버 배포 완료

결정/이유:
- Chroma 삭제 → MongoDB 삭제 순서 유지 → 중간 실패 시 벡터만 날아가고 DB는 보존
- reportlab CID 폰트(HYSMyeongJo-Medium) 사용 → 한글 깨짐 방지
- MeetingEvidenceOrchestrationService 요청마다 새 인스턴스 생성 → 캐시 혼용 방지

막힌 점:
- meetings.py 머지 충돌 → git checkout origin/dev로 해결
- meeting_repository.py 들여쓰기 오류 → 수정 후 재push

다음 할 일:
- 팀 추가 요청 대응
- 홈서버 SSH 비번 변경 (qwer1234 → 새 비번)

[2026-07-16] AI Review Board 개발 일지

한 일:
- 스토리지 10GB → 50GB 확장 (NCP 콘솔 + resize2fs)
- mongo-tunnel.service 자동화 (서버 재시작 시 MongoDB SSH 터널 자동 연결)
- schema_version 2.1.0 업데이트 (PR #57)
- RAG-006 similar_success_cases 연동 (PR #59)
- meetings.py 머지 충돌 해결 (======= / >>>>>>> 마커 제거)
- dev 브랜치 최신화 후 누락 패키지 전체 설치 및 서비스 복구
  (langchain-text-splitters, sentence-transformers, torch CPU, accelerate 등)
- NCP 배포 완료
- 서버 로그 점검 (이상 없음)

결정/이유:
- mongo-tunnel.service systemd 등록 → 수동 터널 연결 실수 방지 및 서버 재시작 시 자동 복구
- torch CPU 버전 설치 → GPU 패키지 용량 이슈로 디스크 절약

막힌 점:
- dev 브랜치 머지 후 누락 패키지로 서비스 실행 안 됨 → 패키지 순차 설치로 해결
- pip cache 용량 문제 → pip cache purge 반복 적용

다음 할 일:
- DOC-006: 문서 원문/추출문 미리보기
- RPT-005: 평가 결과 PDF 내보내기
- PRJ-004: 프로젝트 삭제 (용준님 Chroma 삭제 코드 확인 후 진행)

## 2026-07-15

- 한 일:
  - DOC-001~002 문서 업로드 API 구현 및 테스트 완료
  - MongoDB 계정 변경 (sherpa_admin → reviewboard_admin)
  - reviewboard_admin 계정 root 권한 추가
  - Claude Code 세팅 완료
  - NCP 서버 배포 및 dev 브랜치 최신화
  - 용준님 MongoDB 연결 문제 해결
  - 가은님 로그인 오류 해결 (openai 패키지 누락 원인 파악 및 requirements.txt 추가)
  - fail2ban 설치 및 SSH 무차별 접속 차단 설정 (설치 즉시 8개 IP 차단 확인)

- 결정/이유:
  - MongoDB 계정명 전체 변경 → 프로젝트명 리뷰보드로 통일
  - fail2ban maxretry=5, bantime=3600, findtime=600 설정 → 10분 안에 5번 실패 시 1시간 차단
  - openai를 requirements.txt에 추가 → meetings.py에서 import하는데 누락되어 있었음

- 막힌 점:
  - 가은님 로그인 Failed to fetch 원인 추적 → 백엔드 서버 자체가 openai 모듈 없어서 실행 안 되던 거였음

- 다음 할 일:
  - MTG-005: 회의 기록 저장 API
  - INF-003~007: 파일 스토리지, 보안, 로깅
  - 재인님 avatar API 연동
  - 홈서버 SSH 비번 변경 (qwer1234 → 새 비번)

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