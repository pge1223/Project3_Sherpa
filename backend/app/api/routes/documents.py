import asyncio
import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile, status
from starlette.concurrency import run_in_threadpool
from jose import jwt, JWTError
from openai import OpenAI

from ai.rag.converters import (
    ConversionStatus,
    DocumentConversionError,
    build_conversion_metadata,
    cleanup_converted_file,
    convert_if_needed,
)
from ai.rag.loaders.url_loader import load_from_url
from ai.rag.loaders.schemas import UrlExtractionResult, WebPageContent
from ai.rag.loaders.exceptions import (
    InvalidUrlError,
    BlockedUrlError,
    UrlFetchError,
    TooManyRedirectsError,
    DownloadSizeLimitExceededError,
)
from ai.rag.preprocessing.html_cleaner import clean_page_content
from ai.rag.preprocessing.schemas import CleanedWebContent
from ai.rag.parsers import extract_document
from ai.rag.chunking.chunker import chunk_document
from ai.rag.chunking.schemas import ChunkSourceContext, SourceType
from ai.rag.domain.schemas import IndexingContext
from ai.rag.domain.config import DEFAULT_COLLECTION_NAME
from ai.rag.embedding.kure_embedder import KUREEmbedder
from ai.rag.retrieval.chroma_store import ChromaVectorStore
from ai.rag.retrieval.service import RAGIndexingService
from ai.rag.embedding.config import EMBEDDING_VERSION
import chromadb

from app.common.exceptions import BadRequestException, InternalServerException
from app.repositories.project_repository import ProjectRepository
from app.config import settings
from app.models.document import DocumentModel
from app.repositories.document_repository import DocumentRepository
from app.schemas.document import (
    AnnouncementAnalysisResponse,
    AnnouncementEvidence,
    DocumentResponse,
    FetchUrlRequest,
    FetchUrlResponse,
    OfficialFacts,
    StrategicAnalysis,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])
document_repo = DocumentRepository()
project_repo = ProjectRepository()

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

_GENERIC_ERROR_MESSAGE = "URL 문서를 처리하는 중 오류가 발생했습니다."

_indexing_service: RAGIndexingService | None = None
# 가은/Claude(2026-07-15) 시점엔 없었던 락. 용준/Claude(2026-07-18, fetch-url 색인 hang
# 조사): 이 함수는 meetings.py 모듈 임포트 시점(앱 시작, 단일 스레드)에 이미 강제
# 호출되어 정상 상황에선 아래 if _indexing_service is None 체크가 레이스에 걸릴 일이
# 없다 — 하지만 그건 "meetings.py가 지금 이 함수를 호출한다"는 우연에 기대는 것이라,
# 나중에 그 강제 호출이 없어지면 여러 요청이 동시에 처음 호출할 때 KUREEmbedder(모델
# 로딩 비용 큼)가 여러 번 생성되는 TOCTOU 레이스가 생긴다. 방어적으로 락을 건다
# (락 경합은 최초 1회 초기화 이후엔 없음 — 매 요청마다 비용 없음).
_indexing_service_lock = threading.Lock()


def _canonical_chroma_persist_dir() -> str:
    """chromadb.PersistentClient(path=...)의 캐시 키(SharedSystemClient._identifier_to_system)는
    path 문자열을 있는 그대로 딕셔너리 key로 쓴다 — "./chroma_db"와 "chroma_db"처럼 같은
    디렉터리를 가리켜도 문자열이 다르면 완전히 별개의 System(=별개의 SQLite/엔진 연결)이
    두 개 생긴다. 실제로 meetings.py가 str(Path(settings.CHROMA_PERSIST_DIR))로 두 번째
    PersistentClient를 만들고 있었던 게 그 사례였다(2026-07-18, fetch-url 색인 hang 조사
    중 발견 — Windows는 SQLite 파일 잠금이 POSIX와 달리 mandatory라, 서로 모르는 두
    엔진이 같은 물리 파일에 동시 접근하면 즉시 에러 대신 무기한 대기로 이어질 수 있다).
    이 함수로 절대경로로 정규화해 항상 같은 identifier를 쓰도록 강제한다."""
    return str(Path(settings.CHROMA_PERSIST_DIR).resolve())


def _get_indexing_service() -> RAGIndexingService:
    """KUREEmbedder는 모델 로딩 비용이 커서, 첫 호출 시 한 번만 만들어 재사용한다
    (앱 시작 시점에 매번 로딩하지 않도록 지연 초기화). meetings.py 등 다른 모듈은 이
    싱글턴을 직접 재사용해야 한다 — 새로 chromadb.PersistentClient(path=...)나
    KUREEmbedder()를 만들지 말 것 (아래 _get_chroma_client() 참고)."""
    global _indexing_service
    if _indexing_service is None:
        with _indexing_service_lock:
            if _indexing_service is None:
                embedder = KUREEmbedder()
                client = chromadb.PersistentClient(path=_canonical_chroma_persist_dir())
                vector_store = ChromaVectorStore(
                    client=client,
                    collection_name=DEFAULT_COLLECTION_NAME,
                    embedding_model=embedder.model_name,
                    embedding_dimension=embedder.embedding_dimension,
                    embedding_version=EMBEDDING_VERSION,
                )
                _indexing_service = RAGIndexingService(embedder, vector_store)
    return _indexing_service


def _get_chroma_client() -> chromadb.ClientAPI:
    """documents.py 싱글턴이 쓰는 chromadb client를 그대로 반환한다. 같은
    CHROMA_PERSIST_DIR을 가리키는 별도의 chromadb.PersistentClient를 프로세스 안에
    또 만들지 않기 위함 — 다른 컬렉션(예: similar_cases)을 쓰더라도 client(=엔진 연결)
    자체는 공유해야 한다(2026-07-18, meetings.py 중복 PersistentClient 조사 참고)."""
    return _get_indexing_service().vector_store.client


def _parse_chunk_and_index(
    document_id: str, project_id: str, file_path: str, filename: str, document_role: str = "target"
) -> tuple[int, str, dict]:
    """RAG-001~003: 파싱 -> 청킹 -> 임베딩 -> Chroma 저장까지 동기적으로 실행하고
    (색인된 청크 수, 원문 전체 텍스트, 변환 metadata)를 반환한다. CPU-bound라 호출부에서
    threadpool로 감싸 실행해야 한다.
    가은/Claude(2026-07-15): 원문 텍스트도 같이 반환하도록 확장 — analyze_project()가
    submission.text로 쓸 "문서 전체 원문"이 이전엔 어디에도 저장되지 않았다(Chroma는
    벡터/청크 단위라 전체 원문 조회에는 안 맞음).
    가은/Claude(2026-07-16): 용준의 ai/rag/converters(HWP/HWPX -> PDF) 통합
    (ai/rag/converters/INTEGRATION.md 1번 권장 지점 그대로 따름) — HWP/HWPX만 변환해서
    처리용 PDF 경로를 만들고, 그 외 형식은 convert_if_needed()가 None을 반환해 기존 경로를
    그대로 탄다. chunk_context/indexing_context의 filename은 원본 그대로 써서(파라미터
    file_path만 처리용 경로로 바뀜) 색인 메타데이터에 변환 파일명이 노출되지 않는다.
    변환 실패(DocumentConversionError)는 청킹/임베딩 없이 그대로 전파 — 호출부가
    conversion_status=failed 처리를 하도록."""
    source_path = Path(file_path)
    conversion_result = None
    processing_path = source_path
    conversion_metadata: dict = {
        "original_file_type": source_path.suffix.lstrip(".").lower(),
        "processing_file_type": source_path.suffix.lstrip(".").lower(),
        "conversion_status": ConversionStatus.NOT_REQUIRED.value,
        "conversion_error": None,
        "converter_name": None,
        "conversion_duration_ms": None,
    }

    try:
        conversion_result = convert_if_needed(source_path)
        if conversion_result is not None:
            processing_path = conversion_result.converted_path
            conversion_metadata = build_conversion_metadata(conversion_result).model_dump(mode="json")

        extraction = extract_document(processing_path)
        chunk_context = ChunkSourceContext(
            document_id=document_id,
            source_type=SourceType.FILE_UPLOAD,
            source_filename=filename,
        )
        chunking_result = chunk_document(extraction, chunk_context)

        indexing_context = IndexingContext(
            project_id=project_id,
            document_id=document_id,
            document_title=filename,
            document_role=document_role,
        )
        summary = _get_indexing_service().index_chunking_result_with_summary(chunking_result, indexing_context)
        parsed_text = "\n\n".join(block.content for block in extraction.blocks)
        return summary.stored_count, parsed_text, conversion_metadata
    finally:
        cleanup_converted_file(conversion_result)


def _chunk_and_index_webpage(
    document_id: str, project_id: str, url: str, title: str, cleaned: CleanedWebContent
) -> int:
    """가은/Claude(2026-07-15, "다 이어버리자" — 용준 확인 필요): fetch-url이 정제까지만
    하고 멈추던 걸 파일 업로드와 똑같이 청킹/색인까지 잇는다. chunk_document()가 원래부터
    CleanedWebContent를 받도록 설계돼 있어서(ai/rag/chunking/chunker.py) 새 파서/청커를
    만들 필요는 없었다 — SourceType만 URL_WEBPAGE로 바꿔서 그대로 재사용."""
    chunk_context = ChunkSourceContext(
        document_id=document_id,
        source_type=SourceType.URL_WEBPAGE,
        source_url=url,
        document_title=title,
    )
    chunking_result = chunk_document(cleaned, chunk_context)

    indexing_context = IndexingContext(
        project_id=project_id,
        document_id=document_id,
        document_title=title,
        document_role="criteria",
    )
    summary = _get_indexing_service().index_chunking_result_with_summary(chunking_result, indexing_context)
    return summary.stored_count


# 가은/Claude(2026-07-19, INF-007): 공고문 색인(청킹+임베딩+Chroma 저장)이 끝날 때까지
# fetch-url 응답 자체를 막고 있었다 — 정상 케이스도 수 초~수십 초가 걸리고, 예전엔 hang
# 버그(용준/Claude 2026-07-18, Chroma 이중 client 문제 — 지금은 고쳐짐)로 5분+ 무응답도
# 실측됐다. 근본 hang 원인은 고쳐졌지만, "색인이 오래 걸리는 것 자체"와 "타임아웃이
# 아예 없다"는 별개 문제라 — 색인을 백그라운드로 넘기고 타임아웃을 강제한다.
# GET /{project_id}/{document_id}/status(기존 DOC-004 엔드포인트)를 프론트가 폴링해서
# 완료 여부를 확인한다. 아래 상수는 그 백그라운드 색인의 최대 대기 시간(윤한/Claude
# 2026-07-18) — 재발 시 요청이 무기한 걸려있지 않도록 하는 안전장치다.
_WEBPAGE_INDEXING_TIMEOUT_SECONDS = 120


async def _index_webpage_background(
    *,
    document_id: str,
    project_id: str,
    url: str,
    title: str,
    cleaned: CleanedWebContent,
) -> None:
    """색인을 백그라운드로 돌리고 끝나면 documents 컬렉션의 status를 patch한다
    (meetings.py의 _synthesize_chair_background()와 동일 패턴). asyncio.wait_for로
    타임아웃을 걸지만, run_in_threadpool로 넘긴 실제 스레드 자체를 강제 종료하지는
    못한다 — 진짜 hang이면 그 스레드는 백그라운드에 남아있게 되고, 여기선 "기다리는 걸
    포기하고 실패로 기록"까지만 보장한다(요청/폴링 쪽을 무한 대기에서 풀어주는 게 목적)."""
    _index_started = time.time()
    logger.info("[fetch-url] 색인(백그라운드) 시작 document_id=%s url=%s", document_id, url)
    try:
        stored_count = await asyncio.wait_for(
            run_in_threadpool(_chunk_and_index_webpage, document_id, project_id, url, title, cleaned),
            timeout=_WEBPAGE_INDEXING_TIMEOUT_SECONDS,
        )
        status_value = "indexed" if stored_count > 0 else "indexed_empty"
        logger.info(
            "[fetch-url] === 색인(백그라운드) 완료 === document_id=%s elapsed=%.1fs stored_count=%d",
            document_id,
            time.time() - _index_started,
            stored_count,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "[fetch-url] 색인(백그라운드) 타임아웃: document_id=%s (%ds 초과) elapsed=%.1fs",
            document_id,
            _WEBPAGE_INDEXING_TIMEOUT_SECONDS,
            time.time() - _index_started,
        )
        status_value = "indexing_timeout"
    except Exception:
        logger.exception(
            "[fetch-url] 색인(백그라운드) 실패: document_id=%s elapsed=%.1fs",
            document_id,
            time.time() - _index_started,
        )
        status_value = "indexing_failed"
    await document_repo.update_fields(document_id, {"status": status_value})


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


async def verify_project_owner(project_id: str, user_email: str):
    project = await project_repo.find_by_id_and_user(project_id, user_email)
    if not project:
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다")
    return project


def _apply_cleaning(page_content: WebPageContent) -> tuple[WebPageContent, CleanedWebContent]:
    """clean_page_content()는 CleanedWebContent(title/fetched_at/encoding 없음)를 반환하므로,
    원본 WebPageContent의 title/fetched_at/encoding/is_js_rendered_suspected는 그대로 두고
    blocks/text/text_length만 정제 결과로 교체한 새 WebPageContent를 만든다
    (기존 UrlExtractionResult.page_content 응답 계약 유지).
    가은/Claude(2026-07-15): 원본 CleanedWebContent도 같이 반환하도록 확장 — chunk_document()가
    바로 이 타입을 받도록 설계돼 있어서(merge된 WebPageContent가 아니라) 색인하려면 필요하다."""
    cleaned = clean_page_content(page_content)
    cleaned_text = "\n\n".join(block.content for block in cleaned.cleaned_blocks)
    merged = page_content.model_copy(update={
        "blocks": cleaned.cleaned_blocks,
        "text": cleaned_text,
        "text_length": len(cleaned_text),
    })
    return merged, cleaned


# DOC-004: URL 문서 수집
# 가은/Claude(2026-07-19, INF-007): 색인(청킹+임베딩)이 끝날 때까지 이 응답 자체를 막지
# 않는다 — project_id가 있으면 document_id를 즉시 만들어 반환하고, 색인은
# _index_webpage_background()로 넘긴다. 프론트는 응답에 담긴 page_content/attachments/
# warnings로 문서 행을 바로 그리고, document_status가 "indexing"이면
# GET /{project_id}/{document_id}/status(DOC-004, 기존 엔드포인트)를 폴링한다.
@router.post("/fetch-url", response_model=FetchUrlResponse)
async def fetch_url(
    request: FetchUrlRequest,
    authorization: Optional[str] = Header(None, alias="authorization"),
) -> FetchUrlResponse:
    user_email = get_current_user(authorization)

    try:
        result = await run_in_threadpool(load_from_url, request.url)
    except (InvalidUrlError, BlockedUrlError, TooManyRedirectsError) as exc:
        raise BadRequestException(detail=str(exc)) from exc
    except (UrlFetchError, DownloadSizeLimitExceededError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except Exception:
        logger.exception("URL 문서 수집 중 예상하지 못한 오류가 발생했습니다: url=%s", request.url)
        raise InternalServerException(detail=_GENERIC_ERROR_MESSAGE)

    document_id: Optional[str] = None
    document_status: Optional[str] = None

    if result.page_content is not None:
        try:
            merged_page_content, cleaned = await run_in_threadpool(_apply_cleaning, result.page_content)
        except Exception:
            logger.exception("HTML 정제 중 예상하지 못한 오류가 발생했습니다: url=%s", request.url)
            raise InternalServerException(detail=_GENERIC_ERROR_MESSAGE)
        result = result.model_copy(update={"page_content": merged_page_content})

        # 가은/Claude(2026-07-15, "다 이어버리자"): project_id가 있으면 공고문도 기획서
        # 업로드와 동일하게 색인 + documents 컬렉션 저장까지 잇는다. 없으면(과거 호출
        # 호환) 조회만 하고 끝낸다 — 프론트가 project_id를 꼭 보내도록 같이 바꿨다.
        # 윤한/Claude(2026-07-18, INF-007): 색인을 이 요청 안에서 await하면 요청이 색인
        # 소요 시간만큼(수십 초~) 붙잡혀 있었다 — status="indexing"으로 저장만 해두고
        # asyncio.create_task()로 넘긴 뒤 즉시 응답한다(meetings.py의 위원장 종합 백그라운드
        # 이관과 동일 패턴). 프론트는 document_status="indexing"이면 document_id로
        # /{project_id}/{document_id}/status를 폴링해 최종 상태를 확인해야 한다.
        if request.project_id:
            title = merged_page_content.title or request.url
            document = DocumentModel(
                project_id=request.project_id,
                user_email=user_email,
                original_filename=title,
                stored_filename=request.url,
                file_path=request.url,
                file_size=merged_page_content.text_length,
                mime_type="text/html",
                status="indexing",
                source_type="url",
                document_role="criteria",
                parsed_text=merged_page_content.text,
                # 가은/Claude(2026-07-18): 실측(sotong.go.kr) — 평가기준이 본문이 아니라
                # HWP 요강 파일에만 있는 공고가 실제로 있었다. 재접속 후에도(getDocuments())
                # "직접 받아서 올려주세요" 안내를 다시 보여줄 수 있게 저장해둔다.
                unsupported_attachments=[
                    {"url": a.url, "file_name": a.file_name, "reason": a.reason}
                    for a in result.unsupported_attachments
                ]
                or None,
            )
            document_id = await document_repo.create(document)
            document_status = "indexing"
            asyncio.create_task(
                _index_webpage_background(
                    document_id=document_id,
                    project_id=request.project_id,
                    url=request.url,
                    title=title,
                    cleaned=cleaned,
                )
            )

    return FetchUrlResponse(**result.model_dump(), document_id=document_id, document_status=document_status)


# DOC-001: 문서 업로드
@router.post("/{project_id}", response_model=DocumentResponse)
async def upload_document(
    project_id: str,
    file: UploadFile = File(...),
    source_type: str = Form("pdf"),
    # 가은/Claude(2026-07-15): "target"(평가 대상 문서/기획서, 기본값 — 기존 호출 호환) |
    # "criteria"(공고문 파일 업로드 탭). DocumentUploadPage.jsx의 두 드롭존과 대응된다.
    document_role: str = Form("target"),
    authorization: Optional[str] = Header(None, alias="authorization"),
):
    user_email = get_current_user(authorization)
    await verify_project_owner(project_id, user_email)

    # DOC-005: 업로드 파일 검증
    # HWP/HWPX는 ai/rag/converters(#45)가 내부적으로 PDF로 변환해 처리한다
    # (ai/rag/converters/INTEGRATION.md 5번 참고) — 화이트리스트에도 포함해야 한다.
    ALLOWED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".hwp", ".hwpx"}
    ALLOWED_MIME_TYPES = {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/x-hwp",
        "application/haansofthwp",
        "application/vnd.hancom.hwp",
        "application/haansofthwpx",
        "application/vnd.hancom.hwpx",
    }
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

    file_ext = os.path.splitext(file.filename or "")[1].lower()
    if file_ext not in ALLOWED_EXTENSIONS:
        raise BadRequestException(detail=f"지원하지 않는 파일 형식입니다. 허용: PDF, DOCX, PPTX, HWP, HWPX")

    # HWP/HWPX는 OS/브라우저에 등록된 표준 MIME이 없어 대부분 application/octet-stream으로
    # 전송된다 — 확장자 화이트리스트를 이미 통과했으므로 이 두 확장자는 MIME 검사를 건너뛴다.
    if file_ext not in {".hwp", ".hwpx"} and file.content_type and file.content_type not in ALLOWED_MIME_TYPES:
        raise BadRequestException(detail=f"지원하지 않는 MIME 타입입니다: {file.content_type}")

    content = await file.read()
    if len(content) == 0:
        raise BadRequestException(detail="빈 파일은 업로드할 수 없습니다")
    if len(content) > MAX_FILE_SIZE:
        raise BadRequestException(detail=f"파일 크기가 너무 큽니다. 최대 50MB까지 허용됩니다")

    stored_filename = f"{uuid.uuid4()}_{file.filename}"
    file_path = os.path.join(UPLOAD_DIR, stored_filename)

    with open(file_path, "wb") as f:
        f.write(content)

    # DOC-002: 문서 메타데이터 저장
    document = DocumentModel(
        project_id=project_id,
        user_email=user_email,
        original_filename=file.filename,
        stored_filename=stored_filename,
        file_path=file_path,
        file_size=len(content),
        mime_type=file.content_type or "application/octet-stream",
        source_type=source_type,
        document_role=document_role,
    )

    result = await document_repo.create(document)

    # RAG-001~003: 파싱 -> 청킹 -> 임베딩 -> Chroma 색인 (실패해도 업로드 자체는 성공으로 유지)
    try:
        stored_count, parsed_text, conversion_metadata = await run_in_threadpool(
            _parse_chunk_and_index, result, project_id, file_path, file.filename, document_role
        )
        document.status = "indexed" if stored_count > 0 else "indexed_empty"
        document.parsed_text = parsed_text
        document.conversion_metadata = conversion_metadata
        await document_repo.update_fields(
            result,
            {"status": document.status, "parsed_text": parsed_text, "conversion_metadata": conversion_metadata},
        )
    # 가은/Claude(2026-07-16): HWP/HWPX 변환 실패는 일반 색인 실패와 구분한다 —
    # DocumentConversionError.user_message는 서버 경로/명령어 없이 그대로 프론트에
    # 보여줘도 되는 한국어 메시지라(ai/rag/converters/exceptions.py), conversion_metadata에
    # 담아 응답에 실어 보낸다(INTEGRATION.md 6번).
    except DocumentConversionError as exc:
        logger.warning("문서 변환 실패: document_id=%s error=%s", result, exc)
        document.status = "conversion_failed"
        document.conversion_metadata = {
            "original_file_type": os.path.splitext(file.filename)[1].lstrip(".").lower(),
            "processing_file_type": None,
            "conversion_status": "failed",
            "conversion_error": exc.user_message,
            "converter_name": None,
            "conversion_duration_ms": None,
        }
        await document_repo.update_fields(
            result, {"status": document.status, "conversion_metadata": document.conversion_metadata}
        )
    except Exception:
        logger.exception("문서 색인 중 오류가 발생했습니다: document_id=%s", result)
        document.status = "indexing_failed"
        await document_repo.update_status(result, document.status)

    return DocumentResponse(
        id=result,
        project_id=document.project_id,
        user_email=document.user_email,
        original_filename=document.original_filename,
        stored_filename=document.stored_filename,
        file_path=document.file_path,
        file_size=document.file_size,
        mime_type=document.mime_type,
        source_type=document.source_type,
        status=document.status,
        created_at=document.created_at,
        updated_at=document.updated_at,
        document_role=document.document_role,
        conversion_metadata=document.conversion_metadata,
        unsupported_attachments=document.unsupported_attachments,
    )


# DOC-003: 프로젝트 문서 목록 조회
@router.get("/{project_id}", response_model=list[DocumentResponse])
async def get_documents(
    project_id: str,
    authorization: Optional[str] = Header(None, alias="authorization"),
):
    user_email = get_current_user(authorization)
    await verify_project_owner(project_id, user_email)
    documents = await document_repo.find_by_project_id(project_id)

    return [
        DocumentResponse(
            id=str(d["_id"]),
            project_id=d["project_id"],
            user_email=d["user_email"],
            original_filename=d["original_filename"],
            stored_filename=d["stored_filename"],
            file_path=d["file_path"],
            file_size=d["file_size"],
            mime_type=d["mime_type"],
            source_type=d["source_type"],
            status=d["status"],
            created_at=d["created_at"],
            updated_at=d["updated_at"],
            document_role=d.get("document_role", "target"),
            conversion_metadata=d.get("conversion_metadata"),
            unsupported_attachments=d.get("unsupported_attachments"),
        )
        for d in documents
    ]


# 가은/Claude(2026-07-21): 실측 요청 — /board에서 URL/파일로 올린 공고문·평가기준
# 문서를 잘못 올렸을 때 지울 수 있게. PRJ-004(프로젝트 전체 삭제, projects.py)와
# 같은 순서(Chroma 벡터 청크 -> MongoDB 문서 레코드)를 문서 1건 단위로 좁힌 것 — 벡터
# 삭제는 ChromaVectorStore.delete_document()를 직접 쓴다(RAGIndexingService는
# delete_project만 감싸고 있어 서비스 계층에 새 메서드를 추가하는 대신 documents.py
# 안에서 기존 _get_indexing_service() 싱글턴을 그대로 재사용).
@router.delete("/{project_id}/{document_id}")
async def delete_document(
    project_id: str,
    document_id: str,
    authorization: Optional[str] = Header(None, alias="authorization"),
):
    user_email = get_current_user(authorization)
    await verify_project_owner(project_id, user_email)

    document = await document_repo.find_by_id(document_id)
    if not document or document.get("project_id") != project_id:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다")

    indexing_service = _get_indexing_service()
    await run_in_threadpool(indexing_service.vector_store.delete_document, project_id, document_id)
    await document_repo.delete_by_id(document_id)
    return {"message": "문서가 삭제되었습니다"}


# DOC-004: 문서 처리 상태 조회
@router.get("/{project_id}/{document_id}/status")
async def get_document_status(
    project_id: str,
    document_id: str,
    authorization: Optional[str] = Header(None, alias="authorization"),
):
    user_email = get_current_user(authorization)
    await verify_project_owner(project_id, user_email)

    document = await document_repo.find_by_id(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다")

    return {
        "document_id": str(document["_id"]),
        "project_id": document["project_id"],
        "original_filename": document["original_filename"],
        "status": document["status"],
        "updated_at": document["updated_at"],
    }


# DOC-006: 문서 미리보기
@router.get("/{project_id}/{document_id}/preview")
async def preview_document(
    project_id: str,
    document_id: str,
    authorization: Optional[str] = Header(None, alias="authorization"),
):
    user_email = get_current_user(authorization)
    await verify_project_owner(project_id, user_email)

    document = await document_repo.find_by_id(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다")

    return {
        "original_filename": document["original_filename"],
        "parsed_text": document.get("parsed_text"),
        "status": document["status"],
    }


# 가은/Claude(2026-07-21): "공모전 분석" 화면 실제 데이터 연결 — 실측 제보(사용자,
# 2026-07-21) "URL 넣고 분석 시작 눌렀는데 예시 카드만 나온다"에 대한 대응이자,
# 팀 UX 스펙(사실/전략분석/근거를 분리하고 근거 없는 내용은 지어내지 않는다)을 그대로
# 구현한다. 이미 수집된 criteria 문서(URL/파일, document_role="criteria")의 parsed_text를
# 그대로 근거로 쓴다 — 새 RAG 파이프라인이나 청크 검색은 쓰지 않고 원문 전체(길면 앞부분)를
# 한 번에 LLM에 넣는 단순한 1회성 호출이라 mentor-candidates(get_mentor_candidates)와
# 같은 패턴을 그대로 따른다.
_ANNOUNCEMENT_TRUNCATE_CHARS = 8000


async def _load_criteria_documents_text(project_id: str) -> tuple[str, list[str]]:
    documents = await document_repo.find_by_project_id(project_id)
    criteria_docs = [
        d
        for d in documents
        if d.get("document_role", "target") == "criteria" and d.get("parsed_text")
    ]
    combined = "\n\n---\n\n".join(d["parsed_text"] for d in criteria_docs)
    names = [d["original_filename"] for d in criteria_docs]
    return combined, names


def _build_announcement_analysis_prompt(text: str) -> str:
    truncated = text[:_ANNOUNCEMENT_TRUNCATE_CHARS]
    return f"""당신은 공모전·지원사업 공고문을 분석하는 보조입니다. 아래 공고문 원문을 읽고
announcement_title은 이 공고의 정식 명칭(공모전/지원사업 이름)만 뽑으세요 — 페이지
제목이나 게시판 메뉴명("공지사항", "보도자료" 등)이 아니라 본문에서 실제로 언급되는
공식 명칭을 쓰세요. 명확한 명칭을 못 찾으면 빈 문자열로 두세요(지어내지 마세요).

official_facts는 원문에 실제로 있는 내용만 담으세요 — 원문에 없는 정보는 절대
지어내지 말고, 못 찾은 항목은 빈 배열이나 "미공개"로 남기세요. 특히 evaluation_criteria에
배점이 원문에 없으면 반드시 ["배점 미공개"] 하나만 담으세요.

strategic_analysis는 원문을 근거로 한 당신의 추론(전략적 분석)입니다 — 사실 단정이
아니라 판단임을 유지하고, 근거 없는 단정을 피하세요.

[공고문 원문]
{truncated}

다음 JSON 형식으로만 응답하세요:
{{
  "announcement_title": "...",
  "official_facts": {{
    "eligibility": ["..."],
    "deadline": "...",
    "submission_requirements": ["..."],
    "evaluation_criteria": ["..."],
    "disqualification_rules": ["..."]
  }},
  "strategic_analysis": {{
    "core_intent": "...",
    "winning_points": ["..."],
    "recommended_direction": ["..."],
    "risk_flags": ["..."]
  }},
  "evidence": [
    {{"claim": "...", "source_type": "announcement 또는 inference", "location": "원문 내 위치 또는 null", "confidence": "high, medium, low 중 하나"}}
  ]
}}

evidence는 official_facts/strategic_analysis 중 실제로 중요한 판단 3~6개를 골라 근거를
표시하세요. source_type="announcement"인 항목은 location에 어느 부분에서 확인했는지
짧게 적고(예: "제출 요건 문단"), source_type="inference"인 항목은 location을 null로 두세요."""


def _call_announcement_analysis_llm(prompt: str) -> str:
    profile = (settings.LLM_PROFILE or "dev").lower()
    model = settings.QUALITY_LLM_REVIEWER_MODEL if profile == "quality" else settings.DEV_LLM_REVIEWER_MODEL
    client = OpenAI(api_key=settings.OPENAI_API_KEY, max_retries=1)
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    return resp.choices[0].message.content


def _coerce_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v) for v in value if isinstance(v, (str, int, float)) and str(v).strip()]


@router.post("/{project_id}/announcement-analysis", response_model=AnnouncementAnalysisResponse)
async def get_announcement_analysis(
    project_id: str,
    authorization: Optional[str] = Header(None, alias="authorization"),
):
    user_email = get_current_user(authorization)
    project = await verify_project_owner(project_id, user_email)

    # 가은/Claude(2026-07-21): dynamic_rubric_mapping과 동일한 "프로젝트당 1회 계산 후
    # 캐시" 패턴 — 재방문마다 다시 LLM을 부르지 않는다. 공고문을 나중에 추가/교체해도
    # 자동으로는 무효화하지 않는다(캐시 기준: "이 프로젝트에서 한 번이라도 분석한 적
    # 있는가") — 재분석이 필요하면 지금은 프로젝트를 새로 만들어야 한다.
    cached = project.get("announcement_analysis_cache")
    if cached:
        logger.info("[announcement-analysis] project_id=%s 캐시된 분석 결과 재사용", project_id)
        return AnnouncementAnalysisResponse(**cached)

    text, names = await _load_criteria_documents_text(project_id)
    if not text.strip():
        # 가은/Claude(2026-07-21): 공고문을 하나도 안 넣었으면 LLM을 호출하지 않는다 —
        # "정보 없음"을 지어내는 것보다 화면에서 그 상태 자체를 명시적으로 보여준다.
        # has_announcement: false는 "아직 없음"이라 캐시하지 않는다 — 공고문을 나중에
        # 추가하면 그때는 실제로 분석해야 하기 때문.
        return AnnouncementAnalysisResponse(has_announcement=False)

    prompt = _build_announcement_analysis_prompt(text)
    raw = await run_in_threadpool(_call_announcement_analysis_llm, prompt)

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        parsed = {}

    facts_raw = parsed.get("official_facts") if isinstance(parsed, dict) else None
    facts_raw = facts_raw if isinstance(facts_raw, dict) else {}
    official_facts = OfficialFacts(
        eligibility=_coerce_str_list(facts_raw.get("eligibility")),
        deadline=str(facts_raw.get("deadline") or "미공개"),
        submission_requirements=_coerce_str_list(facts_raw.get("submission_requirements")),
        evaluation_criteria=_coerce_str_list(facts_raw.get("evaluation_criteria")) or ["배점 미공개"],
        disqualification_rules=_coerce_str_list(facts_raw.get("disqualification_rules")),
    )

    strategy_raw = parsed.get("strategic_analysis") if isinstance(parsed, dict) else None
    strategy_raw = strategy_raw if isinstance(strategy_raw, dict) else {}
    strategic_analysis = StrategicAnalysis(
        core_intent=str(strategy_raw.get("core_intent") or ""),
        winning_points=_coerce_str_list(strategy_raw.get("winning_points")),
        recommended_direction=_coerce_str_list(strategy_raw.get("recommended_direction")),
        risk_flags=_coerce_str_list(strategy_raw.get("risk_flags")),
    )

    evidence: list[AnnouncementEvidence] = []
    for item in (parsed.get("evidence") if isinstance(parsed, dict) else None) or []:
        if not isinstance(item, dict) or not item.get("claim"):
            continue
        source_type = item.get("source_type") if item.get("source_type") in ("announcement", "inference") else "inference"
        confidence = item.get("confidence") if item.get("confidence") in ("high", "medium", "low") else "medium"
        evidence.append(
            AnnouncementEvidence(
                claim=str(item["claim"]),
                source_type=source_type,
                location=str(item["location"]) if item.get("location") else None,
                confidence=confidence,
            )
        )

    announcement_title = str(parsed.get("announcement_title") or "").strip() if isinstance(parsed, dict) else ""

    result = AnnouncementAnalysisResponse(
        has_announcement=True,
        announcement_title=announcement_title,
        official_facts=official_facts,
        strategic_analysis=strategic_analysis,
        evidence=evidence,
        has_similar_case_data=False,
        source_document_names=names,
    )
    await project_repo.update_project(project_id, {"announcement_analysis_cache": result.model_dump()})
    return result
