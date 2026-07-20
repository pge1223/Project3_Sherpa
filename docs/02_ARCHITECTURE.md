# 02. Architecture

> ⚠️ **2026-07-20 서비스 방향 전환(진행 중)**: 최신 방향은
> `docs/REVIEW_BOARD_서비스_방향성_정리_20260720.md` 참고. 아래 "2. 데이터
> 처리 흐름"(항상 배치형 위원별 독립 평가 → 위원장 종합)은 그 이전 버전
> 기준이라, "즉시 피드백 기본 + 대화형 위원 소집"으로 바뀐 최신 방향과
> 다를 수 있다 — legacy로 남겨두며 삭제하지 않는다.

## 1. 전체 구조

```text
React Frontend
    ↓ REST / polling
FastAPI Backend
    ├─ Auth / Project / Document API
    ├─ Job Status API
    ├─ Review Result API
    └─ Media API
         ↓
MongoDB + File/Object Storage
         ↓
AI Modules
    ├─ RAG Pipeline
    ├─ LangGraph Meeting
    ├─ Rule-based Score Engine
    └─ TTS / MuseTalk Media Pipeline
```

## 2. 데이터 처리 흐름

```text
문서 업로드
→ 파일 검증·저장
→ 파싱
→ 청킹
→ KURE-v1 임베딩
→ 선정된 Vector DB 저장
→ 도메인 분류
→ 평가기준 추출
→ Persona·Rubric 구성
→ 역할별 Retriever 실행
→ 위원별 독립 평가
→ 규칙 기반 점수 계산
→ 위원장 종합
→ MongoDB 저장
→ media_script 생성
→ TTS
→ MuseTalk
→ 웹 리포트·영상 재생
```

## 3. 주요 모듈

### Frontend

- 프로젝트 목록과 상세
- 문서 업로드
- 도메인 확인·변경
- 진행 상태
- 위원별 평가
- 근거 패널
- 종합 리포트
- 2분할 AI 회의 영상
- 수정 전후 비교

### Backend

- 인증과 권한
- 프로젝트·문서·회의 CRUD
- 비동기 Job 관리
- 파일·미디어 URL 관리
- 모듈 호출과 통합
- 공통 오류 응답

### RAG

- 문서 파서
- 청커
- 임베딩
- Vector DB 저장소 추상화 및 연동
- 역할별 Retriever
- 출처 메타데이터
- 근거 충분성 판정

### Meeting

- LangGraph State
- 위원별 독립 평가 노드
- 점수 엔진 호출
- 위원장 종합 노드
- 수정 우선순위
- media_script 생성

### Score Engine

- 기준별 가중치
- 필수항목 누락 감점
- 점수 범위 정규화
- 계산 버전 관리
- 점수 설명 데이터

### Media

- TTS
- MuseTalk 립싱크
- 발언 순서 큐
- 생성 상태
- 정적 이미지 + TTS 폴백

## 4. 권장 저장소 구조

```text
review-board/
├─ frontend/
├─ backend/
├─ ai/
│  ├─ rag/
│  ├─ meeting/
│  └─ media/
├─ contracts/
│  ├─ review_output.schema.json
│  ├─ meeting_rules.json
│  └─ mocks/
├─ docs/
├─ scripts/
├─ tests/
├─ environment.yml
├─ requirements.txt
├─ .env.example
└─ README.md
```

## 5. 상태 모델 예시

- project: `created | processing | review_ready | reviewing | completed | failed`
- document: `uploaded | parsing | embedded | ready | failed`
- meeting: `pending | retrieving | reviewing | scoring | synthesizing | completed | failed`
- media: `pending | tts_processing | lipsync_processing | completed | fallback | failed`

## 6. 저장 원칙

- MongoDB: 사용자, 프로젝트, 문서 메타데이터, 회의 결과, 점수, Job 상태
- Vector DB: 문서 청크 벡터와 검색 메타데이터. 제품은 RAG 담당자가 비교·선정한다.
- Object Storage 또는 서버 저장소: 원본 문서, 오디오, 영상, PDF 결과
- 모든 결과는 `project_id`, `document_id`, `meeting_id`로 추적한다.

## 7. 통합 원칙

- 모듈은 JSON 계약으로 연결한다.
- 각 모듈은 Mock 입력으로 단독 테스트할 수 있어야 한다.
- 공통 필드 변경은 하위 호환성을 우선한다.
- 비동기 작업은 Job ID와 상태 조회를 제공한다.
- RAG 근거와 최종 평가를 분리 저장한다.

## 8. Vector DB 선택 원칙

Vector DB는 RAG 담당자가 아래 기준으로 비교하고 최종안을 제안한다. 다만 다른 모듈과 배포 환경에 영향을 주므로 관련 담당자 협의와 팀 동의 전에는 확정하지 않는다.

- 예상 문서 수와 청크 수
- 로컬 개발과 NCP 배포 방식
- 영속 저장 및 백업 필요성
- 메타데이터 필터와 하이브리드 검색 지원
- 한국어 임베딩 검색 성능
- 운영 복잡도와 모니터링
- 라이선스와 비용
- LangChain 연동 편의성
- 팀원의 개발·운영 숙련도

다른 모듈은 특정 Vector DB SDK를 직접 호출하지 않고, `store`, `search`, `delete_by_document`, `health_check` 등의 공통 인터페이스를 통해 접근한다.

선정 전 협의 범위:

- 용준: 후보 비교, PoC, 최종안 제안
- 경이: Retriever 요청·응답 JSON과 LangGraph 소비 구조 영향 검토
- 윤한: NCP 배포, 영속성, 백업, 모니터링, 비용 영향 검토
- 가은: 검색 상태·출처·오류 응답이 프론트 계약에 영향을 주는 경우 검토

선정 결과가 공통 계약을 변경하면 `변경 제안 → 영향 담당자 확인 → JSON 예시 공유 → 팀 동의 → schema_version 갱신 → Mock·테스트·문서 갱신 → 코드 반영` 절차를 따른다.
