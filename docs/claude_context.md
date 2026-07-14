# Claude Context — AI Review Board

> 이 문서는 Claude 또는 다른 AI 도구에 AI Review Board 프로젝트의 현재 맥락을 전달하기 위한 인수인계 문서다.  
> 프로젝트 관련 구현·설계 작업을 시작하기 전에 이 문서를 먼저 읽고, 이해한 내용을 요약한 뒤 요청받은 작업만 수행한다.

---

## 1. 프로젝트 식별

- **프로젝트명:** AI Review Board
- **프로젝트 유형:** RAG 기반 다중 AI 전문가 문서 검토 시스템
- **현재 기준일:** 2026-07-14
- **개발 방식:** 공통 JSON 계약과 Mock 데이터를 기반으로 한 병렬 개발
- **주요 실행 환경:** Python 3.12 + Conda
- **주요 배포 환경:** NCP
- **주요 사용자 화면:** React 기반 웹

### 프로젝트 혼동 방지

AI Review Board는 다음 프로젝트와 완전히 별개다.

- 지원금 셰르파
- AI 소설 프로젝트
- 보이스피싱 탐지 프로젝트
- Life Brain
- 그 외 이전 대화의 프로젝트

다른 프로젝트의 요구사항, 기술 스택, 데이터 구조, 역할 분담을 AI Review Board에 임의로 적용하지 않는다.

---

## 2. 프로젝트 목적

사용자가 사업계획서, 기획서, 제안서, 공모전 제출문서 등을 업로드하면 다음 과정을 수행한다.

1. 지원하려는 공고를 URL·PDF·이미지 등으로 등록하고 사용자 작성 문서를 업로드한다.
2. URL은 HTML 본문과 첨부파일을 수집하고, 파일·이미지와 함께 공고 정보를 구조화한 뒤 사용자가 확인·수정한다.
3. 공고 유형·분야·평가축을 분석해 Persona Template Pool에서 AI 위원회를 추천하고 사용자가 최종 구성을 확인한다.
4. 문서를 파싱하고 의미 단위로 청킹한다.
3. 임베딩을 생성해 Vector DB에 저장한다.
4. 문서와 기준에 따라 도메인을 분류한다.
5. 도메인별 AI 위원들이 각자의 평가축으로 독립 검토한다.
6. LangGraph 기반 회의 흐름에서 의견을 종합한다.
7. Python 규칙 기반 점수 엔진으로 평가기준 충족도를 계산한다.
8. 핵심 강점, 문제점, 수정 우선순위와 출처를 제공한다.
9. 핵심 AI 위원 2명의 발언을 TTS와 립싱크 영상으로 재생한다.
10. 최종 결과를 웹 리포트와 PDF로 제공한다.

### 핵심 가치

- 단순한 LLM 감상평이 아니라 **문서 근거 기반 평가**
- 위원별 역할과 평가축이 구분된 **다중 관점 검토**
- LLM의 임의 점수가 아닌 **규칙 기반 점수 계산**
- 의견마다 원문 출처를 연결하는 **추적 가능성**
- 수정 전후 결과를 비교하는 **반복 개선 지원**
- Human AI 연출을 통한 **검토 회의 시각화**

---

## 3. MVP 범위

### 1차 필수 범위

- 사용자 로그인
- 프로젝트 생성 및 조회
- 공고 URL 등록
- 공고 PDF·DOCX·PPTX·이미지 업로드
- 사용자 작성 문서 업로드
- URL HTML 본문 추출과 첨부파일 탐지
- 공고 추출 결과 사용자 확인·수정
- PDF, DOCX, PPTX 파싱
- 문서 청킹 및 임베딩
- 선정된 Vector DB 기반 검색
- 공고 유형·분야·평가기준 자동 분석
- Persona Template Pool 기반 위원 자동 추천
- 추천 위원 사용자 확인·조정
- 도메인별 Persona Card 및 평가 프롬프트
- 위원별 독립 평가
- 위원장 종합
- Python 규칙 기반 점수 계산
- 수정 우선순위 생성
- 회의 결과 저장
- 종합 리포트 및 위원별 상세 의견
- 평가 의견과 원문 출처 연결
- 핵심 AI 페르소나 2명의 TTS 및 MuseTalk 영상
- 2분할 화상회의형 재생 화면
- 영상 실패 시 정적 이미지 + TTS 폴백
- NCP 배포
- URL 수집·파싱·평가·영상 진행 상태 및 오류 표시

### 2차 범위

- 프로젝트 삭제
- 문서 미리보기
- 유사 성공 사례 검색
- 수정 전후 재평가 비교
- 결과 PDF 내보내기
- 점수 산정 근거 상세 분해
- 영상 품질과 배경 연출 개선

### 3차 또는 확장 범위

- 시장·정책 외부 자료 자동 수집
- 가상 사용자 페르소나 평가
- 특정 위원만 재평가
- AI 위원 3~5명 영상화
- 회의장 좌석형 화면
- 동적 그리드 및 영상 캐시
- 관리자용 Persona Template 편집

---

## 4. 확정된 기술 방향

### 공통 개발 환경

- **Python:** 3.12
- **가상환경:** Conda
- **패키지 설치:** Conda 환경 안에서 pip 또는 requirements 파일 사용
- **환경명 권장값:** `review-board`

```bash
conda create -n review-board python=3.12 -y
conda activate review-board
pip install -r requirements.txt
```

### 백엔드 및 인프라

- FastAPI
- MongoDB
- NCP 서버
- NCP Object Storage 또는 서버 저장소
- 비동기 작업 처리
- Job 상태 조회
- OpenAPI 명세
- 환경변수 기반 설정

### RAG

- LangChain
- KURE-v1 임베딩 모델
- Vector DB: 미확정. RAG 담당자가 후보를 비교하고 관련 담당자 협의 후 최종안을 제안
- PyMuPDF
- python-docx
- python-pptx
- 역할별 Retriever
- 문서명, 페이지, 문단 등 출처 메타데이터 유지
- Golden Set 기반 RAG 평가
- Ragas 지표 검토

### AI 회의 및 점수

- LangGraph
- Persona Card
- 위원별 독립 평가
- 위원장 종합
- 평가 결과 JSON
- 점수 계산은 Python 규칙 기반
- LLM은 평가 의견과 설명을 생성하되 최종 계산값을 임의 생성하지 않음

### 프론트엔드

- React 웹
- 데스크톱 우선
- 프로젝트 및 문서 업로드 UI
- 처리 상태 UI
- 위원별 평가 결과 UI
- 출처 패널
- 2분할 AI 화상회의 화면
- 수정 전후 비교 화면
- PDF 다운로드

### AI 영상

- 페르소나 2명
- 서로 구분되는 외형, 복장, 음성, 말투
- TTS
- MuseTalk 립싱크
- 발언 단위 영상
- 생성 완료 후 순차 재생
- 실패 시 정적 이미지 + TTS 폴백

---

## 5. 최종 역할 분담

최신 역할분담 기준으로 아래 담당 경계를 유지한다.

### 5.1 가은 — PM · React 프론트 · 페르소나/프롬프트 기획

#### 핵심 역할

- 전체 일정 및 요구사항 관리
- 사용자 흐름과 화면 구조 설계
- React 프론트 개발
- 도메인별 Persona Card 기획
- 위원별 평가 관점과 말투 정의
- 회의 순서와 회의 문화 정의
- 위원 프롬프트 및 위원장 프롬프트 초안 작성
- Mock API와 샘플 JSON을 이용한 프론트 선개발

#### 주요 작업

- 프로젝트 생성·목록·상세 화면
- 문서 업로드 및 상태 화면
- 도메인 자동 분류 결과와 수동 변경 UI
- AI 회의 진행 화면
- 2분할 AI 화상회의 UI
- 종합 결과 대시보드
- 위원별 상세 평가 패널
- 근거 원문 보기
- 수정 전후 비교 UI
- PDF 다운로드 UI
- Persona Card 명세
- Prompt Spec

#### 주요 산출물

- 요구사항정의서
- 화면흐름도
- 와이어프레임
- React 페이지와 컴포넌트
- Persona Card
- Reviewer Prompt 초안
- Chair Prompt 초안
- Mock JSON

#### 담당 경계

- 프롬프트의 기획 명세를 작성한다.
- LangGraph에서 실행되는 노드와 코드 구현은 경이 담당이다.
- RAG 검색 구현은 용준 담당이다.
- DB와 API 구현은 윤한 담당이다.
- 영상 생성 구현은 재인 담당이다.

---

### 5.2 윤한 — FastAPI · MongoDB · CRUD · NCP

#### 핵심 역할

- FastAPI 통합 허브
- MongoDB 데이터 모델 및 CRUD
- 사용자, 프로젝트, 문서, 회의, 결과 데이터 관리
- 파일 및 미디어 저장 관리
- 모듈 통합 API
- 비동기 작업 상태 관리
- NCP 배포 및 운영
- 인증, 권한, 보안, 로그

#### 주요 작업

- 로그인 및 사용자 인증
- 프로젝트 생성·조회·상세·삭제
- 공고 URL·파일 입력 API
- URL 유효성·보안 검증과 수집 Job
- 접근 차단·로그인 필요·타임아웃 등 실패 처리
- 문서 처리 상태 저장
- 도메인 변경 저장
- 회의 생성 및 결과 저장
- 리포트 조회 API
- 파일·음성·영상 URL 관리
- 프로젝트 소유권 검증
- 파일 확장자·MIME·용량 검증
- RAG·LLM 실행 로그
- 비동기 Job 및 상태 API
- OpenAPI 문서
- NCP 배포

#### 주요 산출물

- FastAPI 서버
- MongoDB 스키마
- CRUD API
- 공통 에러 규격
- 파일 저장 정책
- OpenAPI 명세
- NCP 배포 환경
- 환경변수 예시 파일

#### 담당 경계

- LangGraph 내부 평가 흐름과 점수 계산은 경이 담당이다.
- 문서 청킹과 검색은 용준 담당이다.
- 프론트 UI는 가은 담당이다.
- AI 영상 생성은 재인 담당이다.

---

### 5.3 경이 — LangGraph · 점수 엔진 · 평가 결과 구조

#### 핵심 역할

- LangGraph 회의 워크플로
- 위원 A/B의 독립 평가 흐름
- 위원장 종합 흐름
- 회의 상태 관리
- 평가 결과 JSON 구조
- Python 규칙 기반 점수 계산
- 수정 우선순위
- 수정 전후 비교 기준
- 회의 품질 및 일관성 테스트

#### 주요 작업

- LangGraph State 설계
- 노드와 엣지 구성
- 위원별 독립 평가
- 위원장 종합
- 점수 계산 모듈
- 필수항목 누락 감점
- 항목별 가중치 반영
- 수정 우선순위 Top 3~5
- 회의 진행 단계 관리
- 특정 위원 재평가 확장 구조
- 점수 설명 데이터
- 동일 입력 반복 평가 일관성 테스트
- AI 영상용 `media_script` 생성

#### 주요 산출물

- LangGraph 워크플로
- 평가 결과 JSON Schema
- 점수 계산 모듈
- 회의 상태 모델
- 수정 우선순위 구조
- 점수 설명 구조
- 테스트 케이스

#### 담당 경계

- LLM은 평가 의견을 생성한다.
- 최종 점수는 Python 규칙 엔진이 계산한다.
- 위원장은 새로운 문서 근거를 임의 생성하지 않는다.
- 가은이 작성한 프롬프트 기획안을 실행용 프롬프트로 변환한다.
- RAG 결과는 용준이 제공한 Retriever JSON을 사용한다.
- 저장과 API 공개는 윤한 담당이다.

---

### 5.4 용준 — RAG 파이프라인

#### 핵심 역할

- 문서 파싱
- 청킹
- 임베딩
- 선정된 Vector DB 저장
- 도메인 분류
- 평가기준 추출
- 위원 역할별 검색
- 출처 연결
- RAG 품질 평가

#### 주요 작업

- URL HTML 수집·본문 추출·첨부파일 탐지
- PDF, DOCX, PPTX와 이미지 텍스트 추출
- 페이지·슬라이드·문단 메타데이터 유지
- 청크 크기와 오버랩 실험
- KURE-v1 임베딩
- Vector DB 후보 비교와 PoC, 관련 담당자 협의 및 최종안 제안
- 선정 제품의 컬렉션·인덱스 구성
- 중복 청크 처리
- 역할별 검색 질의 생성
- Top-K 및 metadata filter
- 근거 부족 판정
- 문서명·페이지·인용문 연결
- 스타트업형·정부지원사업형·공모전형 분류
- 유사 성공 사례 검색
- Golden Set 20~50개 구축
- Context Precision/Recall, Faithfulness 등 평가

#### 주요 산출물

- RAG 모듈
- Retriever API 또는 호출 인터페이스
- Vector DB 컬렉션 규칙
- Retriever JSON
- 출처 메타데이터 규격
- RAG 평가 리포트

#### 담당 경계

- Persona와 회의 로직은 담당하지 않는다.
- LangGraph 없이도 샘플 문서로 단독 테스트 가능해야 한다.
- 최종 출력은 경이의 LangGraph가 읽을 수 있는 JSON 계약을 따른다.

---

### 5.5 재인 — AI 휴먼 영상 제작

#### 핵심 역할

- 핵심 AI 페르소나 2명의 영상 자산
- 페르소나별 TTS 음성
- MuseTalk 립싱크
- 2인 회의 영상 재생 규격
- 영상 생성 상태
- 영상 실패 폴백

#### 주요 작업

- 페르소나 A/B 외형과 복장 정의
- 각 페르소나의 Voice ID 선정
- 더미 발언 기반 TTS 테스트
- MuseTalk 립싱크 영상 생성
- MP4 또는 WebM 규격 결정
- 발언 단위 영상 생성
- 발언 순서별 재생 큐
- 한쪽 영상 실패 시 이미지 + TTS 폴백
- 영상 생성 Job 상태
- 2분할 화상회의형 화면 테스트
- 추후 회의장형 화면 확장

#### 주요 산출물

- 페르소나 영상 2종
- 이미지·영상 자산 가이드
- Voice Map
- TTS 및 MuseTalk 노트북/API
- 데모 영상
- 영상 생성 상태 규격
- 폴백 자산

#### 담당 경계

- 실제 회의 문장이 없어도 더미 발언으로 선개발한다.
- 최종 연결 시 `speaker_id`, `text`, `order` 규격을 사용한다.
- LangGraph 회의 로직은 경이 담당이다.
- 저장 및 Job API는 윤한과 연동한다.
- 화면 재생은 가은의 프론트와 연동한다.

---


## 5.6 기능 오너십

기술 담당을 유지하면서 여러 모듈에 걸친 핵심 기능에는 기능 오너를 둔다. 기능 오너는 모든 코드를 직접 작성하지 않고, 계약·일정·부분 통합·End-to-End 완료를 조율한다.

| 기능 | 기능 오너 | 협업 담당 |
|---|---|---|
| 공고 등록·분석 | 용준 | 가은, 윤한 |
| Persona 추천·배정 | 가은 | 용준, 경이, 윤한 |
| AI 회의·평가 | 경이 | 용준, 가은, 윤한 |
| 결과 저장·조회 | 윤한 | 경이, 가은 |
| 결과 리포트 UI | 가은 | 윤한, 경이 |
| AI 위원 영상 | 재인 | 경이, 윤한, 가은 |

### URL 공고 입력 협업

- 용준: HTML 수집·추출·첨부파일 탐지 기술 후보 비교와 최종안 제안
- 윤한: URL 검증, SSRF 방지, 실패·재시도·Job 상태, 원본 스냅샷 저장 정책
- 가은: 파일/URL 입력 UI, 처리 상태, 실패 폴백, 추출 결과 확인·수정 UI
- 경이: 구조화된 공고와 평가축을 이용한 Persona 구성 및 회의 입력 영향 검토

URL 수집 기술이나 상태 모델이 공통 계약에 영향을 주면 팀의 공통 계약 변경 절차를 따른다.

## 6. 병렬 개발 원칙

각 담당자는 다른 사람의 완성본을 기다리지 않는다.

```text
공통 JSON 계약 확정
        ↓
Mock 데이터 작성
        ↓
각 모듈 병렬 개발
        ↓
부분 통합
        ↓
전체 통합
```

### 병렬 개발 흐름

```text
가은: Mock API 기반 React·프롬프트 기획
용준: 샘플 문서 기반 RAG 단독 개발
재인: 더미 발언 기반 영상 선개발
경이: Mock Retriever 기반 LangGraph·점수 로직
윤한: Mock 평가 결과 기반 API·DB·배포
```

### 부분 통합 순서

```text
용준 RAG
  ↕
경이 LangGraph·점수
  ↕
윤한 FastAPI·MongoDB
  ↕
가은 React

경이 media_script
  ↕
재인 AI 영상
  ↕
윤한 미디어 저장·상태 API
  ↕
가은 영상 재생 UI
```

---

## 7. 공통 계약 우선 원칙

아래 값은 구현 전에 팀 전체가 먼저 맞춘다.

- `project_id`
- `document_id`
- `meeting_id`
- `persona_id`
- `speaker_id`
- 문서 유형
- 도메인 값
- 상태 값
- 오류 코드
- Retriever 요청·응답
- 위원 평가 결과
- 점수 계산 입력·출력
- 최종 회의 결과
- 영상 스크립트
- 미디어 Job 결과
- Schema version

### 공통 변경 규칙

공통 JSON 필드나 API 규격을 임의로 변경하지 않는다.

```text
변경 제안
→ 영향받는 담당자 확인
→ JSON 예시 공유
→ 팀 동의
→ schema_version 변경
→ Mock 파일 갱신
→ 코드 반영
```

기존 필드 삭제나 이름 변경보다 새 선택 필드 추가를 우선한다.

### 기술 선택 및 협의 원칙

- 각 기술 영역의 주관 담당자가 후보 비교와 최종 제안을 주도한다.
- 선택 결과가 다른 담당자의 인터페이스, 데이터 구조, 배포 환경 또는 작업 범위에 영향을 주는 경우 단독으로 확정하지 않는다.
- 주관 담당자는 영향받는 담당자에게 후보, 선정 기준, 예상 영향 범위를 공유한다.
- 관련 담당자는 자신의 담당 영역에 대한 검토 의견을 제공한다.
- 관련 담당자 협의와 팀 동의 후 최종 기술을 확정한다.
- 공통 계약 변경이 동반되면 `schema_version`, Mock, 테스트와 관련 문서를 함께 갱신한다.

#### Vector DB 적용

- 주관: 용준 — 후보 비교, PoC, 최종안 제안
- 협의: 경이 — Retriever JSON과 LangGraph 소비 구조 영향 검토
- 협의: 윤한 — NCP 배포, 영속성, 백업, 모니터링, 비용 영향 검토
- 조건부 협의: 가은 — 검색 상태, 출처 표시, 오류 응답 등 프론트 계약 영향 검토
- 팀 동의 전에는 특정 Vector DB를 확정 기술로 표현하지 않는다.

---

## 8. 권장 공통 데이터 예시

### 8.1 RAG 검색 결과

```json
{
  "schema_version": "1.0",
  "project_id": "project_001",
  "document_id": "document_001",
  "persona_id": "business_strategy",
  "query": "시장 문제와 목표 고객이 구체적으로 정의되어 있는가?",
  "evidence": [
    {
      "chunk_id": "chunk_001",
      "document_name": "사업계획서.pdf",
      "page": 3,
      "section": "문제 정의",
      "text": "초기 창업자는 지원사업 정보를 찾는 데 평균적으로 많은 시간을 사용한다.",
      "score": 0.87
    }
  ],
  "evidence_status": "sufficient"
}
```

### 8.2 위원 평가 결과

```json
{
  "schema_version": "1.0",
  "persona_id": "business_strategy",
  "role": "사업전략 전문가",
  "rubric_scores": [
    {
      "criterion_id": "market_need",
      "score": 72,
      "strengths": [
        "문제 상황이 사용자 관점에서 설명되어 있다."
      ],
      "issues": [
        "목표 고객의 범위가 넓다."
      ],
      "suggestions": [
        "예비창업자와 초기 법인 대표를 구분해 작성한다."
      ],
      "evidence_ids": [
        "chunk_001"
      ],
      "confidence": "medium"
    }
  ]
}
```

### 8.3 최종 회의 결과

```json
{
  "schema_version": "1.0",
  "meeting_id": "meeting_001",
  "project_id": "project_001",
  "status": "completed",
  "domain": "startup",
  "reviewer_results": [],
  "score_result": {
    "total_score": 74,
    "score_label": "evaluation_criteria_alignment",
    "calculation_version": "score_v1"
  },
  "agreements": [],
  "disagreements": [],
  "top_revisions": [],
  "evidence": [],
  "media_script": []
}
```

### 8.4 AI 영상 발언 스크립트

```json
{
  "meeting_id": "meeting_001",
  "speaker_id": "business_strategy",
  "speaker_name": "사업전략 전문가",
  "order": 1,
  "text": "현재 목표 고객의 범위가 넓어 우선순위가 불분명합니다.",
  "emotion": "serious"
}
```

### 8.5 미디어 Job 결과

```json
{
  "media_job_id": "media_001",
  "meeting_id": "meeting_001",
  "persona_id": "business_strategy",
  "speaker_order": 1,
  "status": "completed",
  "audio_url": "/media/audio/media_001.wav",
  "video_url": "/media/video/media_001.mp4",
  "fallback_type": null
}
```

---

## 9. 핵심 AI 평가 규칙

1. 위원별 평가는 서로의 결과를 보기 전에 독립적으로 수행한다.
2. 모든 핵심 지적에는 문서 근거를 연결한다.
3. 근거가 부족하면 추정하지 않고 `evidence_status`를 부족으로 표시한다.
4. 공고문이나 기준 문서에 없는 항목을 공식 기준처럼 표현하지 않는다.
5. 위원장은 기존 위원 의견과 근거만 종합한다.
6. 위원장은 새로운 근거를 생성하지 않는다.
7. LLM은 최종 점수를 직접 확정하지 않는다.
8. 점수는 Python 규칙 엔진이 계산한다.
9. 결과 점수는 `당선 확률`이 아니라 `평가기준 충족도`로 표현한다.
10. 동일 입력과 동일 계산 규칙에는 동일 점수 결과가 나와야 한다.
11. 개선안에는 수정 이유와 가능한 경우 대상 문단을 포함한다.
12. 가상 사용자 페르소나 결과는 실제 시장조사로 표현하지 않는다.

---

## 10. Human AI 2인 MVP 규칙

- 영상 페르소나는 핵심 위원 2명만 우선 구현한다.
- 두 페르소나는 역할, 외형, 복장, 배경, 음성, 말투가 구분되어야 한다.
- 실존 인물을 모사하지 않는다.
- 기본 화면은 2분할 화상회의형을 우선한다.
- 이름과 역할 라벨을 항상 표시한다.
- 현재 발언자는 테두리와 마이크 아이콘 등으로 강조한다.
- 색상만으로 발언 상태를 구분하지 않는다.
- 회의는 실시간 통화가 아니라 생성 완료된 결과를 순차 재생한다.
- 사용자에게 `AI 회의 시뮬레이션`임을 명확히 표시한다.
- 한쪽 영상 생성이 실패해도 전체 회의는 계속되어야 한다.
- 실패한 페르소나는 정적 이미지 + 해당 Voice TTS로 전환한다.
- 영상, 자막, 발언자 강조 순서가 일치해야 한다.

---

## 11. 권장 저장소 구조

```text
review-board/
├─ frontend/
├─ backend/
├─ ai/
│  ├─ rag/
│  ├─ meeting/
│  └─ media/
├─ contracts/
│  ├─ schemas/
│  │  └─ review_output.schema.json
│  ├─ mocks/
│  └─ meeting_rules.json
├─ docs/
│  ├─ 00_PROJECT_OVERVIEW.md
│  ├─ 01_REQUIREMENTS.md
│  ├─ 02_ARCHITECTURE.md
│  ├─ 03_DECISIONS.md
│  └─ 04_TEAM_WORKFLOW.md
├─ scripts/
├─ tests/
├─ environment.yml
├─ requirements.txt
├─ .env.example
├─ .gitignore
└─ README.md
```

### 담당자별 주요 폴더

| 담당자 | 주요 작업 폴더 |
|---|---|
| 가은 | `frontend/`, `docs/`, `contracts/mocks/` |
| 윤한 | `backend/`, `scripts/`, 배포 설정 |
| 경이 | `ai/meeting/`, `contracts/schemas/` |
| 용준 | `ai/rag/` |
| 재인 | `ai/media/` |

`contracts/`는 공통 영역이며 변경 시 Pull Request 리뷰가 필요하다.

---

## 12. Conda 환경 파일 권장안

```yaml
name: review-board

channels:
  - conda-forge

dependencies:
  - python=3.12
  - pip
  - pip:
      - -r requirements.txt
```

환경 생성:

```bash
conda env create -f environment.yml
conda activate review-board
```

환경 업데이트:

```bash
conda env update -f environment.yml --prune
```

---

## 13. 현재 확정 사항

- 프로젝트명은 AI Review Board다.
- Python 버전은 3.12다.
- 가상환경은 Conda를 사용한다.
- 프론트는 React 웹이다.
- 백엔드는 FastAPI다.
- 주요 데이터 저장소는 MongoDB다.
- Vector DB 제품은 미확정이며, RAG 담당자가 후보를 비교하고 영향받는 담당자와 협의한 뒤 최종안을 제안한다.
- 임베딩 모델은 KURE-v1을 사용하거나 우선 후보로 둔다.
- AI 회의 흐름은 LangGraph 기반이다.
- 점수 계산은 Python 규칙 기반이다.
- RAG 근거 없는 확정적 평가는 금지한다.
- 공통 JSON Schema와 Mock 데이터로 병렬 개발한다.
- Human AI MVP는 핵심 페르소나 2명을 영상화한다.
- 영상은 TTS + MuseTalk 기반이다.
- 영상 실패 시 이미지 + TTS 폴백을 사용한다.
- 배포는 NCP를 기준으로 한다.
- 담당 업무는 이 문서의 최신 역할분담을 따른다.

---

## 14. 검토 중 또는 미확정 사항

아래 항목은 확정된 것처럼 가정하지 않는다. 담당자가 주도하는 기술 선택이라도 다른 모듈이나 배포 환경에 영향을 주면 관련 담당자 협의와 팀 동의 후 확정한다.

- 최종 LLM 모델
- LLM 모델별 온도와 토큰 설정
- KURE-v1 최종 확정 여부와 GPU 실행 방식
- Vector DB 제품 및 운영 방식. 용준 주관, 경이·윤한 협의 후 팀 동의 필요
- 비동기 작업 도구의 최종 선택
- Celery, FastAPI Background Task, 별도 Queue 중 선택
- TTS 서비스 최종 선택
- MuseTalk 실행 서버 또는 Colab 운영 방식
- Object Storage 최종 사용 여부
- 인증 방식의 세부 구현
- 회의에 참여하는 전체 위원 수
- 영상화하지 않는 위원 결과의 표시 방식
- 최종 도메인별 Persona Card 내용
- 공고 평가항목 가중치 추출 방식
- Golden Set 최종 문항 수
- RAG 검색 Top-K와 유사도 임계값
- PDF 생성 라이브러리
- 프론트 상태관리 라이브러리

---

## 15. Claude 작업 규칙

Claude는 아래 규칙을 따른다.

1. AI Review Board와 다른 프로젝트를 섞지 않는다.
2. 확정 사항을 임의로 변경하지 않는다.
3. 미확정 사항을 확정된 것처럼 작성하지 않는다.
4. 기존 JSON Schema와 API 계약을 먼저 확인한다.
5. 담당자 경계를 임의로 변경하지 않는다.
6. 구현 전 파일 경로와 영향 범위를 명시한다.
7. 기존 파일 수정과 신규 파일 생성을 구분한다.
8. 구조 변경이 필요하면 바로 수정하지 말고 아래를 먼저 설명한다.
   - 현재 구조
   - 문제점
   - 제안 구조
   - 변경 영향 범위
9. 누락된 정보는 임의 생성하지 않고 `가정`으로 표시한다.
10. 모든 답변은 한국어로 작성한다.
11. 근거 없는 기술 결정을 프로젝트의 확정 결정처럼 기록하지 않는다.
12. Mock 기반 병렬 개발 원칙을 유지한다.
13. 공통 계약 변경 시 관련 담당자와 파일을 함께 표시한다.
14. 점수 계산 로직과 LLM 자연어 평가를 분리한다.
15. 사용자에게 보이는 점수는 당선 가능성이 아니라 평가기준 충족도다.
16. 담당자가 기술 선택을 주도하더라도 다른 담당 영역에 영향이 있으면 단독으로 확정하지 않는다.
17. 제안 단계의 기술을 확정 사항처럼 문서화하지 않는다.

---

## 16. Claude 최초 응답 지시문

이 파일을 Claude에게 전달할 때 아래 지시문을 함께 사용한다.

```text
첨부된 claude_context.md는 AI Review Board 프로젝트의 현재 인수인계 문서다.

먼저 문서를 읽고 코드를 작성하거나 구조를 변경하지 말고, 다음 항목만 정리해라.

1. 프로젝트 목적
2. 1차 MVP 범위
3. 확정된 기술 스택
4. 담당자별 역할과 담당 경계
5. 전체 데이터 처리 흐름
6. 병렬 개발 방식
7. 공통 JSON 계약에서 먼저 확정해야 하는 항목
8. 현재 미확정 사항
9. 네가 작업할 때 지켜야 할 규칙

요약 내용이 문서와 일치하는지 확인받은 뒤, 내가 요청하는 작업만 수행해라.
다른 프로젝트의 내용을 섞지 마라.
답변은 한국어로 작성해라.
```

---

## 17. 전체 처리 흐름

```text
사용자 로그인
→ 프로젝트 생성
→ 평가 대상 문서 업로드
→ 기준 문서 업로드
→ 문서 검증 및 저장
→ 텍스트 파싱
→ 청킹
→ KURE-v1 임베딩
→ 선정된 Vector DB 저장
→ 도메인 분류
→ 공고 평가기준 추출
→ Persona Card 및 동적 rubric 구성
→ 위원 역할별 RAG 검색
→ 위원별 독립 평가
→ Python 규칙 기반 점수 계산
→ 위원장 종합
→ 수정 우선순위 생성
→ MongoDB 저장
→ AI 영상용 media_script 생성
→ TTS
→ MuseTalk 영상 생성
→ 2인 AI 회의 순차 재생
→ 종합 리포트 및 근거 표시
→ 수정 문서 재평가 및 비교
→ PDF 내보내기
```

---

## 18. 문서 우선순위

Claude 또는 다른 AI가 저장소에 접근할 수 있다면 다음 순서로 확인한다.

1. `claude_context.md`
2. `README.md`
3. `docs/00_PROJECT_OVERVIEW.md`
4. `docs/01_REQUIREMENTS.md`
5. `docs/02_ARCHITECTURE.md`
6. `docs/03_DECISIONS.md`
7. `docs/04_TEAM_WORKFLOW.md`
8. `contracts/schemas/review_output.schema.json`
9. `contracts/meeting_rules.json`
10. `contracts/mocks/`
11. 각 모듈의 README
12. 실제 구현 코드
13. 테스트 코드

서로 충돌하는 내용이 있을 경우 최신 요구사항정의서와 공통 계약을 우선하고, 충돌 내용을 사용자에게 알린다.

## 19. URL 공고 입력 및 상태 모델

- 공고는 URL, PDF, DOCX, PPTX, 이미지로 등록할 수 있다.
- URL은 직접 평가에 사용하지 않고 HTML·첨부파일을 수집해 구조화한 뒤 사용자 확인을 거친다.
- document 상태 권장값: `submitted | validating | fetching_url | fetched | parsing | embedded | ready | failed`.
- source_type 권장값: `url | pdf | docx | pptx | image`.
- 실패 사유는 `invalid_url`, `access_denied`, `login_required`, `robots_blocked`, `timeout`, `dynamic_render_required`, `extraction_failed` 등을 구분한다.
- URL 수집 계약은 향후 `document_source.schema.json` 또는 `ingestion_job.schema.json`으로 분리할 수 있다.
- 현재 `review_output.schema.json`은 평가 결과 계약이므로 URL 입력 추가만으로 schema_version을 변경하지 않는다.
