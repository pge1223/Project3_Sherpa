import logging
import os
import uuid

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile, status
from starlette.concurrency import run_in_threadpool
from jose import jwt, JWTError

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
from app.config import settings
from app.models.document import DocumentModel
from app.repositories.document_repository import DocumentRepository
from app.schemas.document import DocumentResponse, FetchUrlRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])
document_repo = DocumentRepository()

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


def _parse_chunk_and_index(document_id: str, project_id: str, file_path: str, filename: str) -> int:
    """RAG-001~003: 파싱 -> 청킹 -> 임베딩 -> Chroma 저장까지 동기적으로 실행하고
    색인된 청크 수를 반환한다. CPU-bound라 호출부에서 threadpool로 감싸 실행해야 한다."""
    extraction = extract_document(file_path)
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
    return summary.stored_count


def get_current_user(authorization: str) -> str:
    try:
        token = authorization.replace("Bearer ", "")
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다")


def _apply_cleaning(page_content: WebPageContent) -> WebPageContent:
    """clean_page_content()는 CleanedWebContent(title/fetched_at/encoding 없음)를 반환하므로,
    원본 WebPageContent의 title/fetched_at/encoding/is_js_rendered_suspected는 그대로 두고
    blocks/text/text_length만 정제 결과로 교체한 새 WebPageContent를 만든다
    (기존 UrlExtractionResult.page_content 응답 계약 유지)."""
    cleaned = clean_page_content(page_content)
    cleaned_text = "\n\n".join(block.content for block in cleaned.cleaned_blocks)
    return page_content.model_copy(update={
        "blocks": cleaned.cleaned_blocks,
        "text": cleaned_text,
        "text_length": len(cleaned_text),
    })


# DOC-004: URL 문서 수집
@router.post("/fetch-url", response_model=UrlExtractionResult)
async def fetch_url(
    request: FetchUrlRequest,
    authorization: str = Header(..., alias="authorization"),
) -> UrlExtractionResult:
    get_current_user(authorization)

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
            cleaned_page_content = await run_in_threadpool(_apply_cleaning, result.page_content)
        except Exception:
            logger.exception("HTML 정제 중 예상하지 못한 오류가 발생했습니다: url=%s", request.url)
            raise InternalServerException(detail=_GENERIC_ERROR_MESSAGE)
        result = result.model_copy(update={"page_content": cleaned_page_content})

    return result


# DOC-001: 문서 업로드
@router.post("/{project_id}", response_model=DocumentResponse)
async def upload_document(
    project_id: str,
    file: UploadFile = File(...),
    source_type: str = Form("pdf"),
    authorization: str = Header(..., alias="authorization"),
):
    user_email = get_current_user(authorization)

    stored_filename = f"{uuid.uuid4()}_{file.filename}"
    file_path = os.path.join(UPLOAD_DIR, stored_filename)

    content = await file.read()
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
    )

    result = await document_repo.create(document)

    # RAG-001~003: 파싱 -> 청킹 -> 임베딩 -> Chroma 색인 (실패해도 업로드 자체는 성공으로 유지)
    try:
        stored_count = await run_in_threadpool(
            _parse_chunk_and_index, result, project_id, file_path, file.filename
        )
        document.status = "indexed" if stored_count > 0 else "indexed_empty"
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
    )


# DOC-003: 프로젝트 문서 목록 조회
@router.get("/{project_id}", response_model=list[DocumentResponse])
async def get_documents(
    project_id: str,
    authorization: str = Header(..., alias="authorization"),
):
    user_email = get_current_user(authorization)
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
        )
        for d in documents
    ]
