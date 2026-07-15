import logging

from fastapi import APIRouter, Header, HTTPException, status
from fastapi.concurrency import run_in_threadpool

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

from app.api.routes.projects import get_current_user
from app.common.exceptions import BadRequestException, InternalServerException
from app.schemas.document import FetchUrlRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])

_GENERIC_ERROR_MESSAGE = "URL 문서를 처리하는 중 오류가 발생했습니다."


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
