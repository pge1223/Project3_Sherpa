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
5. retrieved_evidence는 rubric 각 기준의 criterion_name으로 RAGIndexingService.search()를
   돌려 모은 것이다(documents.py의 기존 인스턴스를 그대로 재사용 — KUREEmbedder를 두 번
   로딩하지 않기 위해). ai/rag/role_retrieval(역할 기반 재정렬)은 이번엔 안 썼다 — M4
   그래프가 애초에 위원 전체에게 같은 evidence 리스트를 통째로 넘기도록 설계돼 있어서
   (reviewer_prompt.txt가 "본인 전문 범위만 상세히 검토"를 프롬프트 레벨에서 지시함),
   지금 구조에 맞지 않는다. 위원별로 다른 검색 결과를 주고 싶다면 이건 경이의 그래프
   설계를 바꿔야 하는 별도 논의가 필요하다.
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
- retrieved_evidence를 위원별로 다르게 줄지(ai/rag/role_retrieval 활용) — 그러려면
  LangGraph reviewer 노드가 개별 evidence를 받도록 경이의 그래프 구조 변경이 필요
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
import json
import logging
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from jose import jwt, JWTError
from openai import OpenAI
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.models.meeting import MeetingModel
from app.repositories.document_repository import DocumentRepository
from app.repositories.meeting_repository import MeetingRepository
from app.repositories.project_repository import ProjectRepository

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
    run_meeting,
)
# from graph import (
#     assemble_meeting_graph,
#     assemble_reevaluation_graph,
#     initial_state,
#     reevaluation_state,
# )
from prompts import get_persona_card  # noqa: E402

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
_CHAIR_MARKER = "위원장(review_chair)입니다"


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


def _load_rubric_mapping(domain: str) -> dict:
    path = _PERSONAS_DIR / f"rubric_mapping_{domain}.json"
    if not path.exists():
        raise HTTPException(
            status_code=400,
            detail=f"'{domain}' 도메인의 평가기준 템플릿(rubric_mapping_{domain}.json)이 아직 없습니다.",
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _search_evidence_for_rubric(project_id: str, rubric: dict, top_k: int = 3) -> list[dict]:
    """rubric 기준별로 RAGIndexingService.search()를 돌려 근거를 모은다. documents.py의
    기존 인스턴스를 재사용한다(KUREEmbedder 중복 로딩 방지)."""
    from app.api.routes.documents import _get_indexing_service

    service = _get_indexing_service()
    evidence_by_chunk: dict[str, dict] = {}
    for criterion in rubric["criteria"]:
        results = service.search(query=criterion["criterion_name"], project_id=project_id, top_k=top_k)
        for r in results:
            if r.chunk_id in evidence_by_chunk:
                continue
            evidence_by_chunk[r.chunk_id] = {
                "chunk_id": r.chunk_id,
                "document_name": r.metadata.get("document_title") or r.metadata.get("source_filename"),
                "page": r.metadata.get("location_number"),
                "section": r.metadata.get("section_title"),
                "text": r.content,
                "score": r.score,
            }
    return list(evidence_by_chunk.values())


@router.post("/{project_id}/analyze")
async def analyze_project(project_id: str, authorization: Optional[str] = Header(None, alias="authorization")):
    user_email = get_current_user(authorization)

    project = await project_repo.find_by_id(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")
    domain = project["doc_type"]

    documents = await document_repo.find_by_project_id(project_id)
    target_docs = [d for d in documents if d.get("document_role", "target") == "target" and d.get("parsed_text")]
    if not target_docs:
        raise HTTPException(
            status_code=400, detail="평가 대상 문서(기획서)를 먼저 업로드하고 색인이 끝난 뒤 분석을 시작하세요."
        )
    target_doc = target_docs[0]
    submission = {"document_name": target_doc["original_filename"], "text": target_doc["parsed_text"]}

    mapping = _load_rubric_mapping(domain)
    rubric = build_rubric(mapping)
    committee = mapping["committee"]

    retrieved_evidence = _search_evidence_for_rubric(project_id, rubric)

    meeting_id = f"MTG-{project_id}-{uuid.uuid4().hex[:8]}"
    llm_call = _build_real_llm_call(meeting_id)

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
    # run_meeting()이 그래프 조립부터 v2 문서 조립까지 다 해준다. 내부 graph.stream()도
    # 동기 함수라 threadpool로 감싸는 건 그대로 유지.
    document = await run_in_threadpool(
        run_meeting,
        meeting_id=meeting_id,
        project_id=project_id,
        document_id=target_doc["_id"],
        title=project.get("title") or submission["document_name"],
        rubric_mapping=mapping,
        submission=submission,
        retrieved_evidence=retrieved_evidence,
        llm_call=llm_call,
    )

    # MTG-005: 회의 결과 저장. committee/submission/retrieved_evidence도 이제 진짜 값이라
    # reevaluate_reviewer()가 재구성 없이 그대로 이어받을 수 있다.
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
        schema_version="2.0.0",
    )
    await meeting_repo.create(meeting)

    return document


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
