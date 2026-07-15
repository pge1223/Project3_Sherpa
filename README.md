# AI Review Board

RAG 기반 다중 AI 전문가 문서 검토 시스템이다. 사용자가 사업계획서, 기획서, 제안서, 공모전 제출문서와 평가기준 문서를 업로드하면, 도메인별 AI 위원들이 근거 기반으로 독립 평가하고 위원장이 의견을 종합한다. 최종 점수는 LLM이 임의로 생성하지 않고 Python 규칙 엔진이 계산한다.

## 핵심 기능

- PDF, DOCX, PPTX 문서 업로드 및 파싱
- KURE-v1 임베딩과 Chroma 기반 검색
- 도메인 자동 분류 및 수동 변경
- Persona Card 기반 다중 AI 위원 평가
- LangGraph 기반 회의 흐름
- Python 규칙 기반 평가기준 충족도 계산
- 근거 문서, 페이지, 문단 연결
- 수정 우선순위 및 수정 전후 비교
- 핵심 AI 위원 2명의 TTS + MuseTalk 회의 영상
- React 웹 리포트와 PDF 내보내기

## 기술 스택

- Python 3.11
- Conda
- React
- FastAPI
- MongoDB
- LangChain / LangGraph
- KURE-v1
- Chroma
- PyMuPDF / python-docx / python-pptx
- TTS / MuseTalk
- NCP

## 로컬 환경

```bash
conda env create -f environment.yml
conda activate review-board
pip install -r requirements.txt
```

## 문서 읽는 순서

1. `README.md`
2. `docs/00_PROJECT_OVERVIEW.md`
3. `docs/01_REQUIREMENTS.md`
4. `docs/02_ARCHITECTURE.md`
5. `docs/03_DECISIONS.md`
6. `docs/04_TEAM_WORKFLOW.md`
7. `contracts/review_output.schema.json`
8. `contracts/meeting_rules.json`

## 프로젝트 혼동 방지

이 프로젝트는 지원금 셰르파, AI 소설, 보이스피싱 탐지, Life Brain과 별개다. 다른 프로젝트의 요구사항, 기술 결정, 역할 분담을 섞지 않는다.
