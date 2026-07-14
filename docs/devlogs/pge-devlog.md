# pge Devlog

## 2026-07-14

- 한 일:
  - 레포를 지원금 셰르파 → AI Review Board로 전면 리셋 (main/dev 히스토리 초기화)
  - CLAUDE.md 및 팀 워크플로 문서 정리, `feature/pge` 통해 PR
  - `docs/`, `contracts/`, `frontend/`, `backend/`, `ai/` 등 모노레포 폴더 스캐폴딩
  - frontend에 Vite+React 기본 골격 추가, `npm run dev` 로컬 확인 완료
  - `environment.yml`이 `requirements.txt` 없어서 `conda env create` 실패하는 문제 발견 → 최소 의존성으로 `requirements.txt` 추가, `fix/requirements-txt` 브랜치로 PR
- 결정/이유:
  - `.gitignore`의 `models/` 규칙이 `backend/app/models/` 코드 폴더까지 가려서 `ai/**/models/`로 좁힘
  - `requirements.txt`는 배포용 공통 파일이라 최종본은 윤한과 상의 필요 — 지금은 로컬 개발 unblock용 최소 버전만 커밋
- 막힌 점:
  - 로컬에 `gh` CLI가 없어서 PR은 커맨드로 못 열고 compare 링크로 대체
- 다음 할 일:
  - `fix/requirements-txt` PR 팀 리뷰 받기
  - frontend 실제 페이지(로그인/업로드/회의실/리포트) 작업 이어가기
