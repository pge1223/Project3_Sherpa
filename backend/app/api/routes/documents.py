import logging
import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile, status
from starlette.concurrency import run_in_threadpool
from jose import jwt, JWTError

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
from app.schemas.document import DocumentResponse, FetchUrlRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])
document_repo = DocumentRepository()
project_repo = ProjectRepository()

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

_GENERIC_ERROR_MESSAGE = "URL 문서를 처리하는 중 오류가 발생했습니다."

_indexing_service: RAGIndexingService | None = None


def _get_indexing_service() -> RAGIndexingService:
    """KUREEmbedder는 모델 로딩 비용이 커서, 첫 호출 시 한 번만 만들어 재사용한다
    (앱 시작 시점에 매번 로딩하지 않도록 지연 초기화)."""
    global _indexing_service
    if _indexing_service is None:
        embedder = KUREEmbedder()
        client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
        vector_store = ChromaVectorStore(
            client=client,
            collection_name=DEFAULT_COLLECTION_NAME,
            embedding_model=embedder.model_name,
            embedding_dimension=embedder.embedding_dimension,
            embedding_version=EMBEDDING_VERSION,
        )
        _indexing_service = RAGIndexingService(embedder, vector_store)
    return _indexing_service


def _parse_chunk_and_index(
    document_id: str, project_id: str, file_path: str, filename: str
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
    )
    summary = _get_indexing_service().index_chunking_result_with_summary(chunking_result, indexing_context)
    return summary.stored_count


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
@router.post("/fetch-url", response_model=UrlExtractionResult)
async def fetch_url(
    request: FetchUrlRequest,
    authorization: Optional[str] = Header(None, alias="authorization"),
) -> UrlExtractionResult:
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
        if request.project_id:
            document = DocumentModel(
                project_id=request.project_id,
                user_email=user_email,
                original_filename=merged_page_content.title or request.url,
                stored_filename=request.url,
                file_path=request.url,
                file_size=merged_page_content.text_length,
                mime_type="text/html",
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
            try:
                stored_count = await run_in_threadpool(
                    _chunk_and_index_webpage,
                    document_id,
                    request.project_id,
                    request.url,
                    merged_page_content.title or request.url,
                    cleaned,
                )
                status_value = "indexed" if stored_count > 0 else "indexed_empty"
            except Exception:
                logger.exception("공고문 색인 중 오류가 발생했습니다: document_id=%s", document_id)
                status_value = "indexing_failed"
            await document_repo.update_fields(document_id, {"status": status_value})

    return result


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
            _parse_chunk_and_index, result, project_id, file_path, file.filename
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
