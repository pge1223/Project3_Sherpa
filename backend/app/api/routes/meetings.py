"""
가은/Claude, 2026-07-15, "다 이어버리자" — 전체 파이프라인 실연결
=====================================================================
이 파일은 원래 경이님의 M4(LangGraph 노드 조립)가 나오기 전, 프론트 "분석 시작" 흐름을
끊지 않기 위한 fixture 스텁이었다. M4가 머지되고 MTG-005(회의 저장)/MTG-007(위원 재평가)도
붙은 뒤, analyze_project()의 계산 자체(RAG 검색 -> rubric/committee 구성 -> LangGraph 실행)
까지 실제로 연결했다. 무엇이 어디서 왔는지, 어디를 임의로 판단했는지 정리해둔다.

[analyze_project() 실제 흐름]
1. project_repo.find_by_id(project_id)로 프로젝트의 doc_type을 읽어 domain으로 쓴다
   (competition/government_support/startup — 프론트 DocumentUploadPage.jsx DOC_TYPE_OPTIONS
   과 동일한 값).
2. document_repo.find_by_project_id(project_id)로 문서를 모아 document_role별로 나눈다
   ("target"=평가 대상 문서/기획서, "criteria"=공고문). role 필드는 이번에 새로 추가했다
   (app/models/document.py) — 이게 없으면 어떤 문서를 실제로 채점할지 구분할 방법이
   없었다.
3. rubric/committee는 ai/meeting/personas/rubric_mapping_{domain}.json을 그대로 쓴다
   (경이의 build_rubric(), 가은의 PER-002 매핑). 공고문에서 평가기준을 자동 추출하는
   기능은 아직 없어서(용준 담당, notice_criteria 추출 자체가 미착수) 이 정적 템플릿을
   기본값으로 채택했다 — Q1/Q2 논의에서 나온 대로 "당장은 rubric_mapping을 docType으로
   바로 골라 쓰는" 방식.
   **rubric_mapping_startup.json은 아직 없다** — startup 도메인 프로젝트는 지금 400으로
   막힌다. competition/government_support만 됨(우선순위도 competition이 1순위로 정해짐).
4. submission은 document_role="target"인 첫 문서의 parsed_text를 쓴다(문서가 여러 개면
   첫 번째만 — 여러 문서를 어떻게 합칠지는 정해진 바 없어서 협의 필요).
5. [2026-07-17 갱신] evidence_context/evidence_callback은 MeetingEvidenceOrchestrationService
   (ai/rag/orchestration, RAG-003 RoleAwareRetrievalService·RAG-004 EvidenceLinkingService·
   RAG-005 EvidenceSufficiencyService 조립, README.md 참고)가 만든다 — persona_id마다
   role_mapping.py의 role_id로 검색하고(위원별로 다른 검색 결과), 위원 의견 생성 후
   evidence_callback으로 근거 연결·근거충족도 게이팅까지 붙인다. retrieved_evidence(flat)는
   evidence_context를 chunk_id 기준으로 평탄화한 값으로, run_meeting() 자체엔 안전망
   fallback일 뿐이고 MeetingModel 저장/MTG-007 rerun_reviewer()/ask_committee()가 쓰는
   레거시 flat 경로용이다(_flatten_evidence_context()). role_retrieval_service는
   documents.py의 기존 RAGIndexingService 인스턴스를 재사용한다(KUREEmbedder 중복 로딩
   방지). **domain="government_support"는 role_mapping.py 매핑이 없어 500으로 막힌다**
   (아래 [아직 협의가 필요한 것] 참고).
6. llm_call은 실제 OpenAI 호출이다(_build_real_llm_call). LLM_PROFILE=dev가 기본값이라
   gpt-5-nano로 도는데, 값을 quality로 바꾸면 gpt-5-mini로 바뀐다(backend/.env). 호출
   상한(_MAX_LLM_CALLS_PER_MEETING)과 recursion_limit을 걸어 루프/재시도 폭주를 막았다
   (이 세션에서 LangGraph e2e 테스트할 때 사용자가 명시적으로 요구한 안전장치와 동일).
7. 결과는 MeetingModel/MeetingRepository(MTG-005)로 저장하는데, 이번엔 committee/
   submission/retrieved_evidence도 진짜 값으로 채워진다 — 예전 스텁 버전은 이 세 필드를
   빈 값/추정값으로 채웠었다.

[아직 협의가 필요한 것 — 정리]
- rubric_mapping_startup.json이 없음 (담당: 가은/경이, PER-002 확장 필요)
- submission이 여러 target 문서를 어떻게 합칠지 (지금은 첫 문서만 사용)
- [2026-07-17 해결] retrieved_evidence를 위원별로 다르게 줄지 — MeetingEvidenceOrchestrationService
  (ai/rag/orchestration, RAG-003·004·005) + run_meeting()의 evidence_context/evidence_callback
  연동으로 해결됨(아래 analyze_project() 실제 흐름 5번 참고). 단, domain="government_support"는
  role_mapping.py에 persona_id -> role_id 매핑이 없어(policy_fit/budget_execution 미확정)
  analyze_project() 호출 시 PersonaRoleMappingError(500)로 막힌다 — 이전엔 role_id=None
  semantic-only 검색으로 동작했던 것과 달라진 점. 매핑 확정(용준)/RoleMappingConfig
  완화 여부는 team 확인 필요, 지금은 competition만 실질적으로 동작.
- 응답 시간: committee 인원만큼 실제 OpenAI 호출이 들어가 수십 초~분 단위가 걸린다
  (이 세션 e2e 테스트 실측 3~4분/5회 호출). 지금은 동기 HTTP POST라 그대로 끝날 때까지
  프론트가 기다린다 — 백그라운드 처리(polling/SSE)로 바꿀지는 윤한과 인프라(INF-007)
  차원에서 결정 필요
- backend/.env가 루트 .env와 별도 파일로 존재했고 예전 MONGODB_URL(sherpa_admin, 다른
  프로젝트 잔재로 추정)이 그대로 남아있던 걸 발견 — 이번에 루트 .env와 같은 값으로
  맞췄다. 두 .env 파일을 계속 따로 관리할지, 하나로 합칠지는 윤한 확인 필요

[실제 브라우저 e2e 테스트 중 발견한 버그 — 수정 완료]
graph.invoke()가 동기 함수인데 그냥 호출해서, 실제 OpenAI 호출이 진행되는 수십초~분 동안
asyncio 이벤트 루프 전체가 막혀 서버가 로그인 같은 사소한 요청도 못 받는 상태가 됐다
(health check조차 무응답). documents.py의 _parse_chunk_and_index()와 동일하게
run_in_threadpool()로 감싸 해결. 이건 위 "응답 시간" 항목(백그라운드 처리 여부)과는
별개로, 지금 동기 처리를 유지하더라도 반드시 필요한 최소 수정이었다.

[가은/Claude, 2026-07-16 — 경이의 공식 엔트리포인트로 교체]
dev를 feature/pge에 merge하다가(PR #37) 경이가 run_meeting()/rerun_reviewer()
(ai/meeting/graph/run.py, rerun.py)를 완성해둔 걸 발견했다. run.py 주석에 "backend의
analyze_project()가 이 함수 하나만 호출하면 되도록 만들었다"고 직접 적혀 있어서 —
바로 위 [analyze_project() 실제 흐름] 6번 항목이 설명하던 우리 임시 구현(그래프 직접
조립 + document dict 수동 조립, MTG-007 재평가용 ai/meeting/graph/reevaluate.py)을
걷어내고 경이 버전으로 교체했다. git merge 자체는 충돌이 없었지만(파일이 서로 겹치지
않아서), 같은 역할을 하는 구현이 두 벌 존재하는 "기능적 중복"이라 이번에 정리한 것 —
자세한 건 pge-devlog.md 2026-07-16 항목 참고. 지웠다기보다 무엇을 왜 걷어냈는지
알 수 있게 아래 각 자리에 주석으로 남겨뒀다.
- [수정 완료, 2026-07-16] persona_id 버그: 실제로 브라우저 없이 curl+실제 OpenAI
  호출로 검증하다가 재현 확인함 — analyze() 직후 committee(4명, 신뢰 가능)와
  reviewer_results의 persona_id(전부 LLM이 지어낸 값, 4명 중 실제 id와 하나도 안 겹침)가
  이미 어긋나 있었고, 이 상태에서 reevaluate를 한 번 부르니 rerun.py의
  kept_results 필터(r["persona_id"] != persona_id)가 항상 참이 되어 위원이 교체되지
  않고 reviewer_results가 4개 -> 5개로 늘어나는 것까지 실제로 확인했다. run.py의
  assemble_document()가 (우리가 전에 _reviewer_results_to_list()로 방어했던 것과 동일한
  이유로) 딕셔너리 값의 내부 persona_id 대신 키를 신뢰하도록 고쳐서 해결(경이 파일이지만
  가은 승인하에 직접 수정, ai/meeting/graph/run.py 참고).
- 남는 문제: run_meeting()/rerun_reviewer()는 graph.stream()에 recursion_limit을
  넘기지 않는다 — 우리가 쓰던 _RECURSION_LIMIT 상한이 지금 경로에선 적용 안 됨.
- MeetingModel에 document_id 필드를 추가해야 했다 — rerun_reviewer()가
  previous_document["document_id"]를 그대로 요구해서(app/models/meeting.py 참고).
  이 필드 추가 전에 저장된 기존 meetings 레코드로 재평가를 시도하면 KeyError 위험 있음.
"""
import asyncio
import io
import json
import logging
import sys
import time
import uuid
from pathlib import Path
from typing import Optional
from urllib.parse import quote
from xml.sax.saxutils import escape as _xml_escape

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from jose import jwt, JWTError
from openai import OpenAI
from starlette.concurrency import run_in_threadpool

import chromadb

from ai.rag.embedding.kure_embedder import KUREEmbedder
from ai.rag.evidence_linking.service import EvidenceLinkingService
from ai.rag.evidence_sufficiency.service import EvidenceSufficiencyService
from ai.rag.orchestration import MeetingEvidenceOrchestrationService
from ai.rag.role_retrieval.service import RoleAwareRetrievalService
from ai.rag.similar_cases import (
    SimilarCaseConfig,
    SimilarCaseRepository,
    SimilarCaseSearchService,
    SimilarCaseSearchRequest,
)
from app.config import settings
from app.models.meeting import MeetingModel
from app.repositories.document_repository import DocumentRepository
from app.repositories.meeting_repository import MeetingRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.meeting import (
    AnalyzeProgress,
    AnalyzeRequest,
    AskAnswer,
    AskQuestionRequest,
    AskQuestionResponse,
    MentorCandidate,
    MentorCandidatesResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["meetings"])
meeting_repo = MeetingRepository()
document_repo = DocumentRepository()
project_repo = ProjectRepository()

_PERSONAS_DIR = Path(__file__).resolve().parents[4] / "ai" / "meeting" / "personas"

_MEETING_DIR = Path(__file__).resolve().parents[4] / "ai" / "meeting"
if str(_MEETING_DIR) not in sys.path:
    sys.path.insert(0, str(_MEETING_DIR))

# 가은/Claude(2026-07-16): PR #37에서 경이가 M4 그래프의 정식 실행 엔트리포인트
# run_meeting()/rerun_reviewer()를 완성했다(ai/meeting/graph/run.py — 주석에
# "analyze_project()가 이 함수 하나만 호출하면 되도록 만들었다"고 명시돼 있음, rerun.py).
# M4가 나오기 전 우리가 임시로 직접 조립했던 assemble_meeting_graph/initial_state(회의
# 실행), assemble_reevaluation_graph/reevaluation_state(우리가 만든
# ai/meeting/graph/reevaluate.py, MTG-007 재평가 임시 구현)는 경이 버전으로 교체하고
# 아래(analyze_project/reevaluate_reviewer)에 주석으로만 남겨둔다.
from graph import (  # noqa: E402
    build_rubric,
    rerun_reviewer,
    run_chair_phase,
    run_meeting,
)
# from graph import (
#     assemble_meeting_graph,
#     assemble_reevaluation_graph,
#     initial_state,
#     reevaluation_state,
# )
from prompts import get_persona_card, render_persona_block  # noqa: E402

# 이 그래프는 committee(최대 8명) + chair 1명이면 끝난다. 그보다 많이 부르면 루프/재시도
# 폭주로 보고 즉시 중단한다(가격과 무관하게 호출 자체가 반복되는 사고 방지 — 세션 중
# 사용자가 명시적으로 요구한 안전장치).
_MAX_LLM_CALLS_PER_MEETING = 10
# 가은/Claude(2026-07-16): run_meeting()/rerun_reviewer()(경이, ai/meeting/graph/run.py·
# rerun.py)는 내부 graph.stream() 호출에 recursion_limit을 넘기지 않는다 — 우리가 쓰던
# 이 상한은 지금 경로에선 적용되지 않고 LangGraph 기본값(25)으로 동작한다. 호출 자체가
# 폭주하는 건 _MAX_LLM_CALLS_PER_MEETING이 llm_call 쪽에서 여전히 막아주지만, 필요하면
# run_meeting()/rerun_reviewer()에 config를 받는 파라미터를 추가하는 걸 경이와 논의 필요.
_RECURSION_LIMIT = 12

# RAG-003/004/005: MeetingEvidenceOrchestrationService가 조립하는 하위 서비스(상태 없음,
# 앱 시작 시 1회 초기화 — ai/rag/orchestration/README.md 2절). documents.py의 기존
# RAGIndexingService 인스턴스를 그대로 주입해 KUREEmbedder를 두 번 로딩하지 않는다(RAG-006과
# 동일 패턴). MeetingEvidenceOrchestrationService 자체는 검색 결과 캐시를 들고 있어 회의
# 1회(요청 1건)마다 새로 만들어야 하므로 여기서 만들지 않는다(analyze_project() 참고).
from app.api.routes.documents import _get_indexing_service  # noqa: E402

_role_retrieval_service = RoleAwareRetrievalService(retrieval_service=_get_indexing_service())
_evidence_linking_service = EvidenceLinkingService()
_evidence_sufficiency_service = EvidenceSufficiencyService()

# RAG-006: similar_success_cases 검색 서비스 (앱 시작 시 1회 초기화)
_similar_case_config = SimilarCaseConfig()
_chroma_client = chromadb.PersistentClient(path=str(Path(settings.CHROMA_PERSIST_DIR)))
_kure_embedder = KUREEmbedder()
_similar_case_repo = SimilarCaseRepository(
    client=_chroma_client,
    collection_name=_similar_case_config.collection_name,
    embedding_model=_kure_embedder.model_name,
    embedding_dimension=_kure_embedder.embedding_dimension,
    embedding_version="embedding_v1",
)
_similar_case_service = SimilarCaseSearchService(_similar_case_repo, _kure_embedder, config=_similar_case_config)

_CHAIR_MARKER = "위원장(review_chair)입니다"

# 가은/Claude(2026-07-17): "진짜 진행률로 바꿔줘" — run_meeting()이 이미 on_progress
# 콜백(MTG-006, ai/meeting/graph/run.py)을 지원하는 걸 발견해서, 별도 백그라운드
# 작업/SSE 없이 이 정도로 가볍게 연결한다. analyze_project()는 여전히 동기 POST라 완료될
# 때까지 응답을 안 주지만, run_meeting()은 run_in_threadpool()의 워커 스레드에서 도는
# 동안 이 프로세스의 이벤트 루프는 자유로워서, 그 사이 GET .../analyze/progress로 폴링하는
# 요청은 정상적으로 처리된다. 프로세스 재시작이나 멀티 워커 배포에선 이 dict가 안 맞지만
# (인메모리, 단일 프로세스 가정) 지금 개발 단계 스케일에선 충분하다 — 여러 워커로
# 늘어나면 Redis 등 공유 저장소로 옮겨야 한다.
_analyze_progress: dict[str, dict] = {}


# 가은/Claude (2026-07-15): 비회원 로그인은 Authorization 헤더 없이 그대로 들어온다 —
# 헤더가 없으면 401 대신 고정 게스트 사용자로 통과시킨다 (projects.py와 동일 컨벤션).
GUEST_USER_EMAIL = "guest@local"


def get_current_user(authorization: Optional[str]) -> str:
    if not authorization:
        return GUEST_USER_EMAIL
    try:
        token = authorization.replace("Bearer ", "")
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다")


def _build_real_llm_call(meeting_id: str):
    """실제 OpenAI 호출. LLM_PROFILE(dev|quality)에 따라 모델을 고르고, 호출마다 로그를
    남기고, 상한을 넘으면 예외로 중단한다."""
    profile = (settings.LLM_PROFILE or "dev").lower()
    if profile == "quality":
        reviewer_model = settings.QUALITY_LLM_REVIEWER_MODEL
        chair_model = settings.QUALITY_LLM_CHAIR_MODEL
    else:
        reviewer_model = settings.DEV_LLM_REVIEWER_MODEL
        chair_model = settings.DEV_LLM_CHAIR_MODEL

    # 429/5xx 자동 재시도가 쌓여 호출이 반복되는 걸 막기 위해 SDK 기본 재시도(2회)보다 낮춘다.
    client = OpenAI(api_key=settings.OPENAI_API_KEY, max_retries=1)
    call_count = {"n": 0}

    def llm_call(prompt: str) -> str:
        call_count["n"] += 1
        if call_count["n"] > _MAX_LLM_CALLS_PER_MEETING:
            raise RuntimeError(
                f"[{meeting_id}] LLM 호출 상한({_MAX_LLM_CALLS_PER_MEETING}회) 초과 — "
                "루프 또는 재시도 폭주 의심, 중단합니다."
            )
        model = chair_model if _CHAIR_MARKER in prompt else reviewer_model
        started = time.time()
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        elapsed = time.time() - started
        logger.info(
            "[%s] LLM 호출 #%d model=%s elapsed=%.1fs usage=%s",
            meeting_id,
            call_count["n"],
            model,
            elapsed,
            resp.usage.model_dump() if resp.usage else None,
        )
        return resp.choices[0].message.content

    return llm_call


# 가은/Claude(2026-07-16): analyze_project()/reevaluate_reviewer()가 경이의
# run_meeting()/rerun_reviewer()를 쓰도록 바뀌면서 이 함수를 부르던 자리가 없어져
# 주석 처리한다. [2026-07-16 수정 완료] 이 함수가 막으려던 것과 같은 문제(LLM이
# persona_id를 "P-STRAT-01"처럼 지어내는 것)가 run.py의 assemble_document()에도
# 있는 걸 실제 호출로 재현 확인해서, 되살리는 대신 ai/meeting/graph/run.py의
# assemble_document() 쪽을 고쳤다(가은 승인하에 직접 수정).
# def _reviewer_results_to_list(reviewer_results: dict) -> list[dict]:
#     """result_state["reviewer_results"]는 {실제 persona_id: v2_result} 딕셔너리다 — 키는
#     committee에서 온 신뢰할 수 있는 값이지만, v2_result 내부의 "persona_id" 필드는 raw LLM
#     출력을 거의 그대로 옮긴 값이라 신뢰할 수 없다(가은/Claude, 2026-07-15 발견: LLM이
#     "business_strategy" 대신 "P-STRAT-01" 같은 걸 지어내는 걸 실제 OpenAI 호출로 확인함
#     — reviewer_prompt.txt/transform.py가 persona_id를 강제하지 않음, 경이 확인 필요).
#     저장/재평가(MTG-007)가 이 필드로 위원을 식별하므로, 리스트로 펼칠 때 항상 딕셔너리
#     키로 덮어써서 신뢰할 수 있는 값만 남긴다."""
#     return [{**v2_result, "persona_id": persona_id} for persona_id, v2_result in reviewer_results.items()]


# 가은/Claude(2026-07-18): "source_document_id가 왜 항상 null이냐"는 질문에 대한 답 —
# 버그가 아니라 지금 구조 자체가 그렇다. rubric은 업로드된 공고문에서 추출되는 게 아니라
# domain(competition/government_support)별 정적 템플릿(rubric_mapping_{domain}.json)을
# 그대로 쓴다(공고문 자동 추출은 용준 담당, notice_criteria 추출 자체가 미착수 —
# meetings.py 상단 큰 주석의 [analyze_project() 실제 흐름] 3번 참고). 그래서 rubric.py의
# build_rubric()이 source_document_id를 항상 None으로 채운다 — 공고문 URL을 아무리 잘
# 수집해도 rubric 자체는 안 바뀐다. 반면 업로드된 공고문은 retrieved_evidence(RAG 검색)
# 근거로는 쓰이므로, "루브릭이 안 먹었다"보다는 "애초에 루브릭에 반영되는 경로가 없다"가
# 정확한 진단이다. 터미널에서 바로 확인할 수 있도록 로그를 남긴다.
def _load_rubric_mapping(domain: str) -> dict:
    path = _PERSONAS_DIR / f"rubric_mapping_{domain}.json"
    if not path.exists():
        raise HTTPException(
            status_code=400,
            detail=f"'{domain}' 도메인의 평가기준 템플릿(rubric_mapping_{domain}.json)이 아직 없습니다.",
        )
    mapping = json.loads(path.read_text(encoding="utf-8"))
    logger.info(
        "[rubric] domain=%s -> %s 정적 템플릿 로드 (공고문에서 자동 추출한 게 아니라 "
        "도메인 고정 기준입니다 — source_document_id는 항상 null). criteria=%d개, committee=%s",
        domain,
        path.name,
        len(mapping.get("rubric", [])),
        mapping.get("committee"),
    )
    return mapping


# 가은/Claude(2026-07-17): 위원별 역할 기반 검색 "배선 교체"(위 이전 버전 주석 참고)를
# RAG-003/004/005 정식 연동으로 교체한다 — MeetingEvidenceOrchestrationService
# (ai/rag/orchestration, README.md 2절 호출 예시 그대로)가 persona_id -> role_id 매핑
# (role_mapping.py, 용준 확정)까지 포함해 evidence_context/evidence_callback을 만들어주므로,
# 여기서 role_id=None을 직접 넘기던 이 함수는 더 이상 필요 없다.
#
# 다만 MeetingModel.retrieved_evidence(주석 참고 — MTG-007 rerun_reviewer()가 evidence_context를
# 모르는 flat 레거시 경로만 지원해 이 필드를 그대로 요구함)와 ask_committee()의
# _render_evidence_lines()는 여전히 flat list가 필요하다. evidence_context를 chunk_id
# 기준으로 평탄화해 채워준다 — reviewer 노드(ai/meeting/graph/nodes/reviewer.py)는
# evidence_context가 있는 위원에겐 이 flat 값을 쓰지 않고(하위호환 fallback 경로만 참조),
# evidence_context가 비어 있는 위원에게만 안전망으로 쓰인다.
def _flatten_evidence_context(evidence_context: list[dict]) -> list[dict]:
    evidence_by_chunk: dict[str, dict] = {}
    for entry in evidence_context:
        for item in entry.get("retrieved_evidence") or []:
            chunk_id = item.get("chunk_id")
            if chunk_id is None or chunk_id in evidence_by_chunk:
                continue
            evidence_by_chunk[chunk_id] = item
    return list(evidence_by_chunk.values())


# 가은/Claude(2026-07-18): "공고문 URL이 실제로 검색에 잡히는지" 확인용 로그 — 원래
# _search_evidence_for_rubric()(role_id=None, 단순 semantic 검색)에 달아뒀던 진단
# 로그인데, RAG-003/004/005 정식 연동(MeetingEvidenceOrchestrationService, 위 주석
# 참고)으로 대체되면서 그 함수 자체가 없어졌다 — evidence_context를 만든 직후(호출부,
# analyze_project())에서 persona_id/criterion_id별로 몇 건 잡혔는지, evidence_status
# (RAG-005 사전 판정)까지 로그로 남기는 걸로 옮긴다.
def _log_evidence_context(project_id: str, evidence_context: list[dict]) -> None:
    total_hits = 0
    for entry in evidence_context:
        hits = entry.get("retrieved_evidence") or []
        total_hits += len(hits)
        hit_names = [
            item.get("document_name") or item.get("source_filename") or "(제목 없음)" for item in hits
        ]
        logger.info(
            "[evidence] persona=%s criterion=%s 검색결과=%d건 sufficiency=%s 출처=%s",
            entry.get("persona_id"),
            entry.get("criterion_id"),
            len(hits),
            (entry.get("sufficiency") or {}).get("evidence_status"),
            hit_names or "(없음)",
        )
    if total_hits == 0:
        logger.warning(
            "[evidence] project_id=%s 전체 %d개 (persona, criterion) 조합에서 근거를 하나도 "
            "못 찾았습니다 — 공고문/기획서가 색인(embedding)까지 끝났는지 documents 컬렉션의 "
            "status를 확인하세요.",
            project_id,
            len(evidence_context),
        )


# 가은/Claude(2026-07-16): analyze_project()와 새 mentor-candidates 엔드포인트(STEP4
# 멘토 추천 화면)가 둘 다 "document_role=target 첫 문서"를 필요로 해서 공용으로 뺐다.
async def _load_target_submission(project_id: str) -> tuple[dict, dict]:
    documents = await document_repo.find_by_project_id(project_id)
    # 가은/Claude(2026-07-18): "공모전 공고 URL 쪽이 색인이 안 된 것 같다" 진단용 —
    # 이 프로젝트에 실제로 몇 개 문서가, 어떤 role/status로 올라와 있는지 분석 시작 시점에
    # 터미널에서 바로 보이게 한다. status가 indexed가 아니면(uploaded/*_failed) 그 문서는
    # RAG 검색에도 안 잡힌다.
    logger.info(
        "[documents] project_id=%s 문서 현황: %s",
        project_id,
        [
            {
                "role": d.get("document_role", "target"),
                "name": d.get("original_filename"),
                "status": d.get("status"),
                "has_parsed_text": bool(d.get("parsed_text")),
            }
            for d in documents
        ]
        or "(문서 없음)",
    )
    target_docs = [d for d in documents if d.get("document_role", "target") == "target" and d.get("parsed_text")]
    if not target_docs:
        raise HTTPException(
            status_code=400, detail="평가 대상 문서(기획서)를 먼저 업로드하고 색인이 끝난 뒤 분석을 시작하세요."
        )
    target_doc = target_docs[0]
    submission = {"document_name": target_doc["original_filename"], "text": target_doc["parsed_text"]}
    return target_doc, submission


# 가은/Claude(2026-07-16): STEP4 "공모전 분석" 화면 — 문서를 rubric_mapping의 고정 후보
# committee(도메인당 4명)에 매칭해 (1) 문서 성격 태그, (2) 후보별 fit_tag를 생성하는 1회성
# LLM 호출. _build_real_llm_call()과 달리 회의 전체를 도는 게 아니라 호출이 정확히 1번뿐이라
# 호출 횟수 상한/위원장-리뷰어 모델 분기가 필요 없어 별도로 둔다 — 모델 설정(dev/quality)만
# 재사용.
_SUBMISSION_TRUNCATE_CHARS = 6000


def _build_characteristics_prompt(submission_text: str, domain: str, candidates: list[dict]) -> str:
    candidate_lines = "\n".join(
        f'- persona_id: "{c["persona_id"]}", 이름: "{c["display_name"]}", 역할: "{c["role"]}"' for c in candidates
    )
    truncated = submission_text[:_SUBMISSION_TRUNCATE_CHARS]
    return f"""당신은 "{domain}" 분야 공모전/지원사업 문서를 분석하는 보조입니다.
아래 문서 내용을 보고 (1) 이 문서의 성격을 짧은 한국어 태그 4~6개로 요약하고, (2) 아래
후보 멘토 각각에 대해 "이 문서에 왜 어울리는지"를 1~4단어의 짧은 한국어 태그로 설명하세요.
새로운 인물을 만들지 말고 반드시 주어진 persona_id를 그대로만 사용하세요.

[문서 내용]
{truncated}

[후보 멘토 목록]
{candidate_lines}

다음 JSON 형식으로만 응답하세요:
{{
  "characteristics": ["태그1", "태그2"],
  "candidates": [{{"persona_id": "...", "fit_tag": "..."}}]
}}"""


def _render_history_lines(history: list[dict] | None) -> str:
    return (
        "\n".join(
            f'- 이전 질문: "{h.get("question", "")}" / 이전 답변: "{h.get("answer", "")}"'
            for h in (history or [])
            if isinstance(h, dict)
        )
        or "(없음)"
    )


# 가은/Claude(2026-07-17): STEP7 "대화형 피드백" 후속 질문 프롬프트. 새 그래프 노드를
# 만드는 대신, 경이의 chair_prompt.txt 도입부("당신은 AI Review Board의
# 위원장(review_chair)입니다...")를 그대로 재사용해 _build_real_llm_call()의
# _CHAIR_MARKER 감지로 위원장 모델(quality 프로필이면 QUALITY_LLM_CHAIR_MODEL)로 자동
# 라우팅되게 한다. 새 채점/근거를 만들지 않고 이미 저장된 회의 결과 안에서만 답하도록
# 프롬프트로 강제한다(위원장 페르소나 카드의 scope.exclude와 동일 원칙).
def _build_followup_prompt(
    question: str,
    history: list[dict] | None,
    submission_text: str,
    reviewer_results: list[dict],
    chair_summary: dict | None,
    top_revisions: list | None,
) -> str:
    truncated = submission_text[:_SUBMISSION_TRUNCATE_CHARS]
    reviewer_lines = (
        "\n".join(
            f'- {r.get("persona_name")}({r.get("role")}): {r.get("summary")}' for r in reviewer_results
        )
        or "(없음)"
    )
    return f"""당신은 AI Review Board의 위원장(review_chair)입니다. 이 회의는 이미 끝났고
아래는 그 결과입니다. 사용자가 결과에 대해 후속 질문을 하면, 이미 나온 위원 의견과
위원장 종합만 근거로 답하세요. 문서나 위원 발언에 없는 새로운 사실·점수를 지어내지
마세요.

[위원장 종합]/[수정 우선순위]는 배경 참고 자료일 뿐입니다 — 그대로 옮겨 쓰지 말고, 이번
질문의 핵심에 초점을 맞춰 답하세요. [이전 대화]에서 이미 한 말을 토씨 그대로 반복하지
말고, 후속 질문이면 앞서 답한 내용에서 한 걸음 더 들어가서 답하세요. 2~4문장으로
간결하게 답하세요.

[검토 대상 문서 요약]
{truncated}

[위원별 검토 요약]
{reviewer_lines}

[위원장 종합]
{json.dumps(chair_summary, ensure_ascii=False) if chair_summary else "(없음)"}

[수정 우선순위]
{json.dumps(top_revisions, ensure_ascii=False) if top_revisions else "(없음)"}

[이전 대화]
{_render_history_lines(history)}

[사용자의 새 질문]
{question}

다음 JSON 형식으로만 응답하세요:
{{"answer": "..."}}"""


# 가은/Claude(2026-07-17): 사용자가 매번 "어느 위원에게 물어볼지" 고르지 않아도 질문
# 내용만 보고 자동으로 관련 위원이 답하게 해달라는 요청(임시 프롬프트 기반, 실제 RAG
# 재검색은 아님) — 라우팅은 1~3명까지 고르게 하고, 특정 분야로 안 좁혀지는 질문은
# review_chair 하나로 fallback한다. "매 질문 강제로 위원 1명만" 고정하면 대화가 길어져도
# 특정 위원만 계속 등장하고 나머지는 한 번도 안 나올 수 있다는 지적이 있었지만, 실제
# 회의에서도 화제가 한쪽에 쏠리면 그런 건 자연스럽다고 보고 강제 로테이션은 넣지 않기로
# 합의(1~3명 선택 정도의 절충).
def _build_routing_prompt(question: str, history: list[dict] | None, reviewer_results: list[dict]) -> str:
    mentor_lines = (
        "\n".join(
            f'- persona_id: "{r.get("persona_id")}", 이름: "{r.get("persona_name")}", '
            f'역할: "{r.get("role")}", 총평: "{r.get("summary")}"'
            for r in reviewer_results
        )
        or "(없음)"
    )
    return f"""아래는 방금 끝난 회의에 참여한 위원들과 각자의 총평입니다. 사용자의 새 질문을 보고
이 질문에 답하기 가장 적합한 위원을 골라주세요.

- 질문이 특정 위원의 전문 분야(역할/총평 참고)와 명확히 관련 있으면 그 위원만 고르세요.
- 질문이 여러 분야에 걸치면 관련된 위원을 최대 3명까지 고르세요.
- 특정 분야로 좁혀지지 않는 전체 총평·진행상황 질문이면 "review_chair" 하나만 고르세요.
- 새 인물을 만들지 말고, 반드시 주어진 persona_id 또는 "review_chair"만 쓰세요.

[참여 위원 목록]
{mentor_lines}

[이전 대화]
{_render_history_lines(history)}

[사용자의 새 질문]
{question}

다음 JSON 형식으로만 응답하세요:
{{"speakers": ["persona_id_또는_review_chair", ...]}}"""


# 가은/Claude(2026-07-17): 위원 개인 페르소나로 후속 질문에 답하는 프롬프트. render_persona_block()
# (경이, ai/meeting/prompts/prompt_loader.py)으로 reviewer_prompt.txt와 같은 방식의 역할/말투
# 블록을 재사용해서 위원장 답변과 캐릭터가 갈리지 않게 한다. "멘토도 전문지식이 있어야 한다"는
# 요청에 대한 임시 대응 — 실제 RAG 재검색 대신, 이미 회의 때 모아둔 공모전 평가기준 근거
# (retrieved_evidence)와 본인이 남긴 검토 내용만 근거로 쓰게 강제한다.
def _render_evidence_lines(retrieved_evidence: list[dict] | None, limit: int = 5) -> str:
    if not retrieved_evidence:
        return "(없음)"
    top = sorted(retrieved_evidence, key=lambda e: e.get("score") or 0, reverse=True)[:limit]
    lines = [f'- [{e.get("document_name") or "출처 불명"}] {(e.get("text") or "")[:300]}' for e in top]
    return "\n".join(lines) or "(없음)"


# 가은/Claude(2026-07-17): "같은 말을 계속 반복한다" 문제 대응 — own_review를
# json.dumps()로 통째로 넣었더니(rubric_scores 전체 + cross_reviews 등) 위원이 새 질문에
# 답하기보다 원래 검토를 거의 그대로 되풀이하는 경향이 있었다. rubric_scores를 "기준명
# (판정): 문제/제안" 정도의 짧은 프로즈로 줄여서 grounding용 배경으로만 쓰이게 하고,
# 프롬프트 지시문에서도 "그대로 옮기지 말라"고 명시했다.
def _render_own_review_lines(own_review: dict | None) -> str:
    if not own_review:
        return "(이 위원은 이번 회의에서 별도 검토를 남기지 않았습니다)"
    lines = [f'총평: {own_review.get("summary", "")}']
    for score in own_review.get("rubric_scores") or []:
        parts = [f'{score.get("criterion_name")}({score.get("judgment")})']
        if score.get("issues"):
            parts.append("문제: " + "; ".join(score["issues"][:2]))
        if score.get("suggestions"):
            parts.append("제안: " + "; ".join(score["suggestions"][:2]))
        lines.append("- " + " / ".join(parts))
    return "\n".join(lines)


def _build_mentor_followup_prompt(
    persona_card: dict,
    question: str,
    history: list[dict] | None,
    submission_text: str,
    own_review: dict | None,
    evidence_lines: str,
) -> str:
    truncated = submission_text[:_SUBMISSION_TRUNCATE_CHARS]
    return f"""{render_persona_block(persona_card)}

이 회의는 이미 끝났고 당신은 이미 이 문서를 검토했습니다. 아래는 당신이 이번 회의에서 남긴 검토
요약과, 검토 때 참고했던 공모전 평가기준 근거입니다 — 이건 배경 참고 자료일 뿐입니다. 사용자가
후속 질문을 하면 본인 캐릭터(위 역할/말투)를 유지하면서, 이번 질문의 핵심에 초점을 맞춰 답하세요.

[당신의 검토 요약]과 [이전 대화]에 이미 쓴 표현을 그대로 옮기거나 반복하지 말고, 질문에 맞는
새로운 각도(구체적 예시, 실행 방법, 우선순위 등)로 설명하세요. 다만 검토 내용과 근거를 벗어난
새로운 사실·점수를 지어내진 마세요. 2~4문장으로 간결하게 답하세요.

[검토 대상 문서 요약]
{truncated}

[당신의 검토 요약]
{_render_own_review_lines(own_review)}

[공모전 평가기준 근거]
{evidence_lines}

[이전 대화]
{_render_history_lines(history)}

[사용자의 새 질문]
{question}

다음 JSON 형식으로만 응답하세요:
{{"answer": "..."}}"""


def _call_characteristics_llm(prompt: str) -> str:
    profile = (settings.LLM_PROFILE or "dev").lower()
    model = settings.QUALITY_LLM_REVIEWER_MODEL if profile == "quality" else settings.DEV_LLM_REVIEWER_MODEL
    client = OpenAI(api_key=settings.OPENAI_API_KEY, max_retries=1)
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    return resp.choices[0].message.content


@router.post("/{project_id}/mentor-candidates", response_model=MentorCandidatesResponse)
async def get_mentor_candidates(project_id: str, authorization: Optional[str] = Header(None, alias="authorization")):
    get_current_user(authorization)

    project = await project_repo.find_by_id(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")
    domain = project["doc_type"]

    _, submission = await _load_target_submission(project_id)

    mapping = _load_rubric_mapping(domain)
    candidates = [
        {"persona_id": pid, "display_name": get_persona_card(pid)["display_name"], "role": get_persona_card(pid)["role"]}
        for pid in mapping["committee"]
    ]

    prompt = _build_characteristics_prompt(submission["text"], domain, candidates)
    raw = await run_in_threadpool(_call_characteristics_llm, prompt)

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        parsed = {}

    characteristics = parsed.get("characteristics")
    if not isinstance(characteristics, list):
        characteristics = []

    # 가은/Claude(2026-07-16): persona_id 신뢰성 버그(같은 날 run.py에서 실제로 재현·수정한
    # 것과 같은 클래스의 문제)가 여기서도 반복되지 않도록, LLM 응답의 persona_id는 매칭에만
    # 쓰고 최종 후보 목록은 우리가 이미 아는 candidates를 기준으로 항상 전원 포함해서
    # 조립한다. 매칭 실패(LLM이 엉뚱한 값을 냈거나 일부를 빼먹은 경우)는 role을 fallback
    # fit_tag로 쓴다.
    fit_tag_by_id: dict[str, str] = {}
    for item in parsed.get("candidates") or []:
        if not isinstance(item, dict):
            continue
        pid, tag = item.get("persona_id"), item.get("fit_tag")
        if isinstance(pid, str) and isinstance(tag, str) and pid in mapping["committee"]:
            fit_tag_by_id[pid] = tag

    return MentorCandidatesResponse(
        characteristics=characteristics[:6],
        candidates=[
            MentorCandidate(
                persona_id=c["persona_id"],
                display_name=c["display_name"],
                role=c["role"],
                fit_tag=fit_tag_by_id.get(c["persona_id"]) or c["role"],
            )
            for c in candidates
        ],
    )


@router.post("/{project_id}/analyze")
async def analyze_project(
    project_id: str,
    request: Optional[AnalyzeRequest] = None,
    authorization: Optional[str] = Header(None, alias="authorization"),
):
    user_email = get_current_user(authorization)

    project = await project_repo.find_by_id(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")
    domain = project["doc_type"]

    target_doc, submission = await _load_target_submission(project_id)

    mapping = _load_rubric_mapping(domain)
    rubric = build_rubric(mapping)
    full_committee = mapping["committee"]

    # 가은/Claude(2026-07-16): STEP4 멘토 선택 화면(mentor-candidates) 연동 — 사용자가
    # 2~4명을 골라 보내면 그 목록만 회의에 참여시킨다. run_meeting()은
    # rubric_mapping["committee"]에서 바로 committee를 읽으므로(ai/meeting/graph/run.py),
    # rubric_mapping을 얕은 복사해서 committee만 바꿔 넘긴다 — rubric/total_max_score는
    # 원본 그대로 둔다. 선택 안 된 위원의 담당 criterion은 아무도 채점하지 않아 자연히
    # 0점 처리된다(ai/meeting/scoring/calculator.py 확인 완료 — 크래시 없음). 배점
    # 재분배는 하지 않기로 확정: weights.py의 total_max_score()가 criteria 배점 합과
    # rubric["total_max_score"]가 다르면 예외를 던지므로, 배점을 건드리는 건 경이의 점수
    # 엔진 영역이라 위험 부담이 크다고 보고 이번엔 안전한 쪽(0점 처리)으로 감.
    committee = (request.committee if request else None) or full_committee
    if not (2 <= len(committee) <= 4) or not set(committee) <= set(full_committee):
        raise HTTPException(
            status_code=400,
            detail=f"committee는 {full_committee} 중 2~4명이어야 합니다.",
        )
    effective_mapping = {**mapping, "committee": committee}

    meeting_id = f"MTG-{project_id}-{uuid.uuid4().hex[:8]}"
    llm_call = _build_real_llm_call(meeting_id)

    # RAG-003/004/005: MeetingEvidenceOrchestrationService는 검색 결과 캐시를 들고 있어
    # 회의 1회(요청 1건)마다 새로 만들어야 한다(README.md "주의" — 재사용하면 다른 회의의
    # 캐시가 섞인다). rubric_mapping은 committee로 필터링하기 전의 원본 mapping을 넘긴다 —
    # iter_persona_criteria()는 rubric_mapping["rubric"]의 모든 criterion을 도므로
    # committee 선택과 무관하다(이전 _search_evidence_for_rubric()도 build_rubric(mapping)의
    # 전체 rubric 기준으로 검색했던 것과 동일한 범위).
    #
    # domain="government_support"는 role_mapping.py에 persona_id -> role_id 매핑이 아직
    # 없어(role_mapping.py 주석 참고, 용준 확인 필요) prepare_meeting_evidence()가
    # PersonaRoleMappingError를 던진다 — competition만 우선 지원되는 지금 상태를 그대로
    # 유지한다(아래에서 잡지 않고 그대로 올려 500으로 드러나게 둔다. RoleMappingConfig로
    # 조용히 완화하는 건 role_mapping.py 팀 정책이라 여기서 임의로 넣지 않는다).
    evidence_service = MeetingEvidenceOrchestrationService(
        role_retrieval_service=_role_retrieval_service,
        evidence_linking_service=_evidence_linking_service,
        evidence_sufficiency_service=_evidence_sufficiency_service,
        top_k=5,
    )
    evidence_context = evidence_service.prepare_meeting_evidence(
        project_id=project_id,
        domain=domain,
        rubric_mapping=mapping,
        trace_id=meeting_id,
    )
    _log_evidence_context(project_id, evidence_context)
    evidence_callback = evidence_service.create_evidence_callback(trace_id=meeting_id)
    # MeetingModel.retrieved_evidence(MTG-007 rerun_reviewer()용 flat 레거시 포맷)와
    # ask_committee()가 여전히 필요로 하는 flat 근거 — evidence_context를 chunk_id 기준으로
    # 평탄화한다(_flatten_evidence_context() 위 주석 참고).
    retrieved_evidence = _flatten_evidence_context(evidence_context)

    # RAG-006: 유사 성공 사례 검색
    try:
        _similar_request = SimilarCaseSearchRequest(
            document_summary=submission["text"][:3000],
            domain=domain,
            evaluation_criteria=[c["criterion_name"] for c in rubric["criteria"]],
            top_k=5,
            trace_id=meeting_id,
        )
        _similar_response = await run_in_threadpool(_similar_case_service.search, _similar_request)
        similar_success_cases = _similar_response.model_dump(mode="json")
    except Exception as e:
        logger.warning(f"RAG-006 similar_success_cases 검색 실패, None으로 진행: {e}")
        similar_success_cases = None

    # 가은/Claude(2026-07-17): progress_token이 있으면 run_meeting()의 on_progress로
    # 스냅샷을 _analyze_progress에 계속 덮어써서, 아래 threadpool 실행이 끝나기 전에도
    # GET .../analyze/progress로 중간 상태를 볼 수 있게 한다. on_progress는
    # run_meeting() 내부(threadpool 워커 스레드)에서 동기로 호출된다 — 여기선 dict
    # 값을 통째로 교체만 하므로 별도 락 없이도 안전하다.
    progress_token = request.progress_token if request else None
    on_progress = None
    if progress_token:
        _analyze_progress[progress_token] = {
            "stage": "준비",
            "reviews_done": 0,
            "reviews_total": len(committee),
            "score_done": False,
            "chair_done": False,
        }

        def on_progress(snapshot: dict) -> None:  # noqa: E306
            _analyze_progress[progress_token] = snapshot

    # 가은/Claude(2026-07-16): 경이의 run_meeting()(ai/meeting/graph/run.py)으로 교체한
    # 자리 — 원래 여기 있던 우리 임시 구현(그래프 직접 조립 + document dict 수동 조립)은
    # 참고용으로 주석 처리해 남겨둔다.
    # graph = assemble_meeting_graph(committee, llm_call)
    # state = initial_state(
    #     meeting_id=meeting_id,
    #     domain=domain,
    #     rubric=rubric,
    #     submission=submission,
    #     committee=committee,
    #     retrieved_evidence=retrieved_evidence,
    # )
    # # graph.invoke()는 동기 함수라 그냥 부르면 실제 OpenAI 호출(수십초~분) 내내 asyncio
    # # 이벤트 루프 전체가 막혀서, 그동안 이 서버는 로그인 같은 사소한 요청도 못 받는다
    # # (실제 브라우저 e2e 테스트 중 발견 — health check조차 무응답이었음).
    # # documents.py의 _parse_chunk_and_index()와 동일하게 threadpool로 감싼다.
    # result_state = await run_in_threadpool(
    #     graph.invoke, state, config={"recursion_limit": _RECURSION_LIMIT}
    # )
    # document = {
    #     "schema_version": "2.0.0",
    #     "meeting_id": meeting_id,
    #     "project_id": project_id,
    #     "document_id": target_doc["_id"],
    #     "title": project.get("title") or submission["document_name"],
    #     "status": "completed",
    #     "domain": domain,
    #     "rubric": rubric,
    #     "reviewer_results": _reviewer_results_to_list(result_state["reviewer_results"]),
    #     "score_result": result_state["score_result"],
    #     "chair_summary": result_state["chair_summary"],
    #     "top_revisions": result_state["top_revisions"],
    #     "evidence": result_state["evidence"],
    #     "media_script": [],
    # }
    #
    # 가은/Claude(2026-07-17, 경이 확인): 위원장 종합을 백그라운드로 미루기로 함 —
    # run_meeting()이 이제 리뷰+채점만 끝내고(include_chair=False) 바로 리턴한다.
    # 이 단계(리뷰+채점)가 실패하면 progress_token을 바로 지우고 예외를 그대로 올린다
    # (기존과 동일). 성공하면 지우지 않는다 — 아래 백그라운드 작업(위원장 종합)이 끝날
    # 때까지 폴링 엔트리를 살려둬야 "결과 정리" 화면이 chair_done을 볼 수 있다.
    try:
        document = await run_in_threadpool(
            run_meeting,
            meeting_id=meeting_id,
            project_id=project_id,
            document_id=target_doc["_id"],
            title=project.get("title") or submission["document_name"],
            rubric_mapping=effective_mapping,
            submission=submission,
            retrieved_evidence=retrieved_evidence,
            llm_call=llm_call,
            evidence_context=evidence_context,
            evidence_callback=evidence_callback,
            similar_success_cases=similar_success_cases,
            on_progress=on_progress,
            include_chair=False,
        )
    except Exception:
        if progress_token:
            _analyze_progress.pop(progress_token, None)
        raise

    # MTG-005: 회의 결과 저장(리뷰+채점만 끝난 상태, chair_summary=None). committee/
    # submission/retrieved_evidence도 이제 진짜 값이라 reevaluate_reviewer()가 재구성
    # 없이 그대로 이어받을 수 있다.
    meeting = MeetingModel(
        project_id=project_id,
        user_email=user_email,
        meeting_id=meeting_id,
        domain=domain,
        title=document["title"],
        status=document["status"],
        document_id=target_doc["_id"],
        rubric=rubric,
        committee=committee,
        submission=submission,
        retrieved_evidence=retrieved_evidence,
        reviewer_results=document["reviewer_results"],
        score_result=document["score_result"],
        chair_summary=document["chair_summary"],
        top_revisions=document["top_revisions"],
        evidence=document["evidence"],
        # 재인/Claude(2026-07-16): 원래 media_script=[]로 따로 고정돼 있어서, run.py의
        # assemble_document()가 실제로 채운 값과 무관하게 DB엔 항상 빈 배열로 저장되고
        # 있었다(캐시된 회의를 다시 불러오면 영상 대본이 사라지는 문제) - document(=
        # run_meeting()의 반환값)에 이미 채워진 값을 그대로 쓰도록 수정.
        media_script=document["media_script"],
        schema_version="2.2.0",
    )
    meeting_doc_id = await meeting_repo.create(meeting)

    # 가은/Claude(2026-07-17, 경이 확인): 위원 재실행 없이 chair 노드만 백그라운드에서
    # 마저 돌리고 끝나면 Mongo 문서를 patch한다 - HTTP 응답은 여기서 기다리지 않고
    # 바로 아래에서 document(리뷰+채점만 있는 버전)를 반환한다. 이 앱은 단일 프로세스
    # 전제(_analyze_progress가 이미 그 전제 위에 있음, 위 주석 참고)라 별도 큐 없이
    # asyncio.create_task로 충분하다.
    asyncio.create_task(
        _synthesize_chair_background(
            meeting_doc_id=meeting_doc_id,
            reviewer_results=document["reviewer_results"],
            rubric=document["rubric"],
            evidence=document["evidence"],
            llm_call=llm_call,
            progress_token=progress_token,
        )
    )

    return document


async def _synthesize_chair_background(
    *,
    meeting_doc_id: str,
    reviewer_results: list,
    rubric: dict,
    evidence: list,
    llm_call,
    progress_token: Optional[str],
) -> None:
    """analyze_project()가 리뷰+채점만 반환한 뒤, 위원장 종합을 이어서 백그라운드로
    돌리고 끝나면 Mongo meetings 문서를 patch한다(가은/Claude 2026-07-17, 경이 확인).
    실패해도 이미 반환된 리뷰 결과 자체는 유효하므로 예외를 삼키고 status만 "failed"로
    남긴다 - 사용자는 "결과 정리" 화면에서 안내를 보고 새로고침하면 된다."""
    try:
        chair_summary, top_revisions = await run_in_threadpool(
            run_chair_phase,
            reviewer_results=reviewer_results,
            rubric=rubric,
            evidence=evidence,
            llm_call=llm_call,
        )
        await meeting_repo.update_result_by_id(
            meeting_doc_id,
            {"chair_summary": chair_summary, "top_revisions": top_revisions, "status": "completed"},
        )
        if progress_token:
            _analyze_progress[progress_token] = {
                **_analyze_progress.get(progress_token, {}),
                "chair_done": True,
            }
    except Exception:
        logger.exception("[CHAIR_BACKGROUND_FAILED] meeting_doc_id=%s", meeting_doc_id)
        await meeting_repo.update_result_by_id(meeting_doc_id, {"status": "failed"})
    finally:
        if progress_token:
            _analyze_progress.pop(progress_token, None)


@router.get("/{project_id}/analyze/progress", response_model=AnalyzeProgress)
async def get_analyze_progress(
    project_id: str,
    token: str,
    authorization: Optional[str] = Header(None, alias="authorization"),
):
    get_current_user(authorization)
    snapshot = _analyze_progress.get(token)
    if snapshot is None:
        # 아직 시작 전(POST가 아직 안 왔거나 이미 끝나서 지워짐)이거나 잘못된 토큰 —
        # 둘 다 구분할 수단이 없으므로 프론트는 POST 자체의 완료 여부로 최종 판단해야 한다.
        return AnalyzeProgress()
    return AnalyzeProgress(**snapshot)


# 가은/Claude(2026-07-16): reevaluate_reviewer()가 경이의 rerun_reviewer()
# (ai/meeting/graph/rerun.py)를 바로 쓰도록 바뀌면서, 저장된 문서를 MeetingState로
# 되돌리던 이 함수는 자리가 없어져 주석 처리한다. rerun_reviewer()는 저장된 v2 문서
# (previous_document)를 그대로 받는 인터페이스라 이런 변환이 필요 없다.
# def _document_to_meeting_state(doc: dict) -> dict:
#     """저장된 meeting 문서(MeetingModel.to_dict())를 reevaluation_state()가 받는
#     MeetingState 모양으로 되돌린다. committee/submission/retrieved_evidence는
#     MeetingModel이 함께 저장해뒀으므로 그대로 읽으면 된다."""
#     reviewer_results = {r["persona_id"]: r for r in doc.get("reviewer_results", [])}
#     return {
#         "meeting_id": doc["meeting_id"],
#         "domain": doc["domain"],
#         "stage": "완료",
#         "rubric": doc["rubric"],
#         "submission": doc.get("submission") or {"document_name": doc.get("title"), "text": ""},
#         "retrieved_evidence": doc.get("retrieved_evidence") or [],
#         "committee": doc.get("committee") or list(reviewer_results.keys()),
#         "reviewer_results": reviewer_results,
#         "evidence": doc.get("evidence", []),
#         "score_result": doc.get("score_result"),
#         "chair_summary": doc.get("chair_summary"),
#         "top_revisions": doc.get("top_revisions"),
#         "failed_node": None,
#     }


@router.post("/{project_id}/reviewers/{persona_id}/reevaluate")
async def reevaluate_reviewer(
    project_id: str, persona_id: str, authorization: Optional[str] = Header(None, alias="authorization")
):
    get_current_user(authorization)

    stored = await meeting_repo.find_latest_by_project_id(project_id)
    if stored is None:
        raise HTTPException(
            status_code=404, detail="이 프로젝트에 저장된 회의 결과가 없습니다. 먼저 분석을 시작하세요."
        )

    committee = stored.get("committee") or [r["persona_id"] for r in stored.get("reviewer_results", [])]
    if persona_id not in committee:
        raise HTTPException(
            status_code=400,
            detail=f"'{persona_id}'는 이 회의의 위원이 아닙니다. committee: {committee}",
        )

    get_persona_card(persona_id)  # 존재하지 않는 persona_id면 여기서 KeyError -> 500으로 드러남

    # 가은/Claude(2026-07-16): 경이의 rerun_reviewer()(ai/meeting/graph/rerun.py)로 교체한
    # 자리 — 원래 여기 있던 우리 임시 구현(전용 재평가 그래프 직접 조립,
    # ai/meeting/graph/reevaluate.py)은 참고용으로 주석 처리해 남겨둔다.
    # reeval_input = reevaluation_state(previous, persona_id)
    # llm_call = _build_real_llm_call(stored["meeting_id"])
    # graph = assemble_reevaluation_graph(persona_id, llm_call)
    # result_state = await run_in_threadpool(
    #     graph.invoke, reeval_input, config={"recursion_limit": _RECURSION_LIMIT}
    # )
    # patch = {
    #     "reviewer_results": _reviewer_results_to_list(result_state["reviewer_results"]),
    #     "score_result": result_state["score_result"],
    #     "chair_summary": result_state["chair_summary"],
    #     "top_revisions": result_state["top_revisions"],
    #     "evidence": result_state["evidence"],
    #     "status": "completed",
    # }
    mapping = _load_rubric_mapping(stored["domain"])
    submission = stored.get("submission") or {"document_name": stored.get("title"), "text": ""}
    retrieved_evidence = stored.get("retrieved_evidence") or []
    llm_call = _build_real_llm_call(stored["meeting_id"])

    document = await run_in_threadpool(
        rerun_reviewer,
        previous_document=stored,
        persona_id=persona_id,
        rubric_mapping=mapping,
        submission=submission,
        retrieved_evidence=retrieved_evidence,
        llm_call=llm_call,
    )

    patch = {
        "reviewer_results": document["reviewer_results"],
        "score_result": document["score_result"],
        "chair_summary": document["chair_summary"],
        "top_revisions": document["top_revisions"],
        "evidence": document["evidence"],
        "status": "completed",
    }
    await meeting_repo.update_result_by_id(stored["_id"], patch)

    return {**stored, **patch, "project_id": project_id}


# MTG-005: 프로젝트 회의 목록 조회
@router.get("/{project_id}/meetings")
async def get_meetings(
    project_id: str,
    authorization: Optional[str] = Header(None, alias="authorization"),
):
    get_current_user(authorization)

    project = await project_repo.find_by_id(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")

    meetings = await meeting_repo.find_by_project_id(project_id)
    return meetings


# MTG-005: 프로젝트 최신 회의 결과 조회
@router.get("/{project_id}/meetings/latest")
async def get_latest_meeting(
    project_id: str,
    authorization: Optional[str] = Header(None, alias="authorization"),
):
    get_current_user(authorization)

    project = await project_repo.find_by_id(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")

    meeting = await meeting_repo.find_latest_by_project_id(project_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="회의 결과가 없습니다. 먼저 분석을 시작하세요.")

    return meeting


# RPT-001: 종합 결과 표시
@router.get("/{project_id}/report")
async def get_project_report(
    project_id: str,
    authorization: Optional[str] = Header(None, alias="authorization"),
):
    get_current_user(authorization)

    project = await project_repo.find_by_id(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")

    meeting = await meeting_repo.find_latest_by_project_id(project_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="회의 결과가 없습니다. 먼저 분석을 시작하세요.")

    return {
        "project_id": project_id,
        "project_title": project.get("title"),
        "domain": meeting.get("domain"),
        "meeting_id": meeting.get("meeting_id"),
        "status": meeting.get("status"),
        "score_result": meeting.get("score_result"),
        "chair_summary": meeting.get("chair_summary"),
        "top_revisions": meeting.get("top_revisions"),
        "reviewer_results": meeting.get("reviewer_results"),
        "evidence": meeting.get("evidence"),
        "created_at": meeting.get("created_at"),
    }


# Claude(2026-07-17): RPT-005 PDF 렌더링. reportlab의 Paragraph는 텍스트를 간이 XML로
# 파싱하므로, LLM/사용자 원문에 "<"/"&" 등이 그대로 들어가면 파싱이 깨진다 — 표시 전
# 항상 xml.sax.saxutils.escape()로 이스케이프한다. Helvetica 등 reportlab 기본 폰트는
# 한글 글리프가 없어 그대로 쓰면 빈 사각형만 나온다 — CID 폰트(HYSMyeongJo-Medium,
# Adobe-Korea1)를 등록해 폰트 파일 임베딩 없이 한글을 그린다(reportlab 표준 방식).
_PDF_FONT = "HYSMyeongJo-Medium"


def _register_pdf_font() -> str:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont

    if _PDF_FONT not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont(_PDF_FONT))
    return _PDF_FONT


def _build_report_pdf(project: dict, meeting: dict) -> bytes:
    """RPT-005: project title + score_result + chair_summary + top_revisions를 담은
    평가 결과 PDF를 만든다. CPU-bound(폰트/레이아웃 계산)라 호출부에서 threadpool로
    감싸 실행한다."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    font_name = _register_pdf_font()
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("KTitle", parent=styles["Title"], fontName=font_name)
    heading_style = ParagraphStyle("KHeading", parent=styles["Heading2"], fontName=font_name)
    body_style = ParagraphStyle("KBody", parent=styles["BodyText"], fontName=font_name, leading=16)

    project_title = project.get("title") or "제목 없음"

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, title=project_title)
    story: list = [Paragraph(_xml_escape(project_title), title_style), Spacer(1, 8 * mm)]

    score_result = meeting.get("score_result") or {}
    if score_result:
        story.append(
            Paragraph(
                f'총점: {score_result.get("total_score")} / {score_result.get("max_score")}', heading_style
            )
        )
        criterion_names = {
            c["criterion_id"]: c["criterion_name"] for c in (meeting.get("rubric") or {}).get("criteria", [])
        }
        rows = [["평가 기준", "점수", "만점"]]
        for b in score_result.get("breakdown") or []:
            criterion_id = b.get("criterion_id")
            rows.append(
                [
                    _xml_escape(criterion_names.get(criterion_id, criterion_id or "")),
                    str(b.get("raw_score")),
                    str(b.get("max_score")),
                ]
            )
        table = Table(rows, colWidths=[100 * mm, 30 * mm, 30 * mm])
        table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), font_name),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                ]
            )
        )
        story.append(Spacer(1, 4 * mm))
        story.append(table)
        story.append(Spacer(1, 8 * mm))

    chair_summary = meeting.get("chair_summary") or {}
    if chair_summary.get("overall_assessment"):
        story.append(Paragraph("위원장 종합", heading_style))
        story.append(Paragraph(_xml_escape(chair_summary["overall_assessment"]), body_style))
        story.append(Spacer(1, 8 * mm))

    top_revisions = meeting.get("top_revisions") or []
    if top_revisions:
        story.append(Paragraph("수정 우선순위", heading_style))
        for rev in sorted(top_revisions, key=lambda r: r.get("priority") or 0):
            line = f'{rev.get("priority")}. {rev.get("title") or ""} — {rev.get("action") or ""}'
            story.append(Paragraph(_xml_escape(line), body_style))
        story.append(Spacer(1, 4 * mm))

    doc.build(story)
    return buffer.getvalue()


# RPT-005: 평가 결과 PDF 내보내기. RPT-001(get_project_report)과 같은 자리에 두되,
# 소유권 확인은 project_repo.find_by_id_and_user()로 한다 — documents.py의
# verify_project_owner()와 동일한 방식으로, 다운로드는 실제 파일이 응답에 실려 나가는
# 만큼 다른 사용자의 프로젝트 문서/식별정보 조회보다 소유권 확인을 더 엄격히 해야 한다는
# 요청에 따름(RPT-001은 project_repo.find_by_id()만 쓰던 것과 다르다).
@router.get("/{project_id}/report/export")
async def export_project_report(
    project_id: str,
    authorization: Optional[str] = Header(None, alias="authorization"),
):
    user_email = get_current_user(authorization)

    project = await project_repo.find_by_id_and_user(project_id, user_email)
    if project is None:
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")

    meeting = await meeting_repo.find_latest_by_project_id(project_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="회의 결과가 없습니다. 먼저 분석을 시작하세요.")

    pdf_bytes = await run_in_threadpool(_build_report_pdf, project, meeting)

    filename = f'{project.get("title") or project_id}_report.pdf'
    # 한글 파일명은 RFC 6266 filename*(UTF-8 percent-encoding)로 넘긴다 — 그냥
    # filename="..."에 non-ASCII를 넣으면 브라우저별로 헤더 파싱이 깨질 수 있다.
    content_disposition = f"attachment; filename*=UTF-8''{quote(filename)}"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": content_disposition},
    )


@router.post("/{project_id}/ask", response_model=AskQuestionResponse)
async def ask_committee(
    project_id: str,
    request: AskQuestionRequest,
    authorization: Optional[str] = Header(None, alias="authorization"),
):
    """STEP7 "대화형 피드백" — 저장된 회의 결과를 근거로 후속 질문에 답한다. 사용자가 어느
    위원에게 물어볼지 직접 고르지 않아도, 질문 내용을 보고 관련 위원 1~3명(또는 특정 분야로
    안 좁혀지면 위원장)이 자동으로 답한다(_build_routing_prompt). 개별 위원 재평가
    (reevaluate_reviewer)와 달리 재채점·재저장 없는 짧은 Q&A라 훨씬 가볍다. 대화 기록은
    서버에 저장하지 않고 매 요청마다 프론트가 history로 넘긴다."""
    get_current_user(authorization)

    stored = await meeting_repo.find_latest_by_project_id(project_id)
    if stored is None:
        raise HTTPException(
            status_code=404, detail="이 프로젝트에 저장된 회의 결과가 없습니다. 먼저 분석을 시작하세요."
        )

    submission = stored.get("submission") or {"document_name": stored.get("title"), "text": ""}
    reviewer_results = stored.get("reviewer_results") or []
    llm_call = _build_real_llm_call(stored["meeting_id"])

    routing_prompt = _build_routing_prompt(request.question, request.history, reviewer_results)
    routing_raw = await run_in_threadpool(llm_call, routing_prompt)
    try:
        speakers = json.loads(routing_raw).get("speakers")
    except (json.JSONDecodeError, TypeError, AttributeError):
        speakers = None

    valid_ids = {r.get("persona_id") for r in reviewer_results} | {"review_chair"}
    speakers = [s for s in speakers if isinstance(s, str) and s in valid_ids] if isinstance(speakers, list) else []
    if not speakers:
        speakers = ["review_chair"]  # 라우팅 실패 시 안전한 기본값

    # 가은/Claude(2026-07-17): 위원별 답변 프롬프트를 먼저 다 만들어두고 asyncio.gather로
    # 동시에 호출한다 — 처음엔 for 루프 안에서 하나씩 await했는데, 라우팅 호출 1번 +
    # 위원마다 순차 호출이 겹쳐서 (최대 1+3=4회) 체감 대기시간이 몇 배로 늘어난다는
    # 지적을 받았다. run_meeting()도 LangGraph superstep에서 위원 리뷰를 병렬로 돌리는
    # 것과 같은 이유로, 여기도 서로 독립적인 호출이라 병렬화해도 안전하다.
    evidence_lines = _render_evidence_lines(stored.get("retrieved_evidence"))
    prompts: list[str] = []
    for persona_id in speakers:
        if persona_id == "review_chair":
            prompts.append(
                _build_followup_prompt(
                    question=request.question,
                    history=request.history,
                    submission_text=submission.get("text", ""),
                    reviewer_results=reviewer_results,
                    chair_summary=stored.get("chair_summary"),
                    top_revisions=stored.get("top_revisions"),
                )
            )
        else:
            own_review = next((r for r in reviewer_results if r.get("persona_id") == persona_id), None)
            prompts.append(
                _build_mentor_followup_prompt(
                    persona_card=get_persona_card(persona_id),
                    question=request.question,
                    history=request.history,
                    submission_text=submission.get("text", ""),
                    own_review=own_review,
                    evidence_lines=evidence_lines,
                )
            )

    raw_results = await asyncio.gather(*(run_in_threadpool(llm_call, prompt) for prompt in prompts))

    answers: list[AskAnswer] = []
    for persona_id, raw in zip(speakers, raw_results):
        try:
            parsed = json.loads(raw)
            answer = parsed.get("answer") if isinstance(parsed, dict) else None
        except (json.JSONDecodeError, TypeError):
            answer = None
        if not isinstance(answer, str) or not answer.strip():
            answer = "답변을 생성하지 못했습니다. 다시 시도해주세요."

        display_name = get_persona_card(persona_id)["display_name"]
        answers.append(AskAnswer(persona_id=persona_id, display_name=display_name, answer=answer))

    return AskQuestionResponse(answers=answers)
