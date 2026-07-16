"""
Custom Exceptions for External Market/Policy Research (RAG-007)
======================================================================
"""

from typing import Optional


class ExternalResearchError(Exception):
    """외부자료 검색 모듈 예외의 공통 베이스."""

    user_message: str = "외부 시장·정책 자료를 처리하지 못했습니다."

    def __init__(self, message: str, *, user_message: Optional[str] = None):
        super().__init__(message)
        if user_message is not None:
            self.user_message = user_message


class ExternalResearchValidationError(ExternalResearchError):
    """검색 요청 또는 외부자료 데이터가 필수 조건을 만족하지 않는 경우.

    Pydantic v2는 필드/모델 validator에서 ValueError/TypeError/AssertionError가 아닌
    예외를 감싸지 않고 그대로 전파하므로, 이 예외를 validator 안에서 raise해도
    pydantic.ValidationError로 감싸이지 않고 이 타입 그대로 전달된다(RAG-006과 동일 패턴).
    """


class ExternalCollectionUnavailableError(ExternalResearchError):
    """외부자료 전용 Chroma 컬렉션에 접근할 수 없거나 기존 설정과 충돌하는 경우."""


class ExternalEvidenceIndexingError(ExternalResearchError):
    """외부자료 색인 중 복구 불가능한 오류가 발생한 경우(개별 자료 스킵과는 별개)."""


class ExternalEvidenceSearchError(ExternalResearchError):
    """검색 자체(임베딩/Chroma 질의)가 실패한 경우. 결과가 0건인 것은 오류가 아니다."""


class ExternalProviderUnavailableError(ExternalResearchError):
    """provider가 비활성화됐거나 필요한 transport/설정이 주입되지 않은 경우."""


class ExternalProviderTimeoutError(ExternalResearchError):
    """provider 호출이 설정된 시간 안에 끝나지 않은 경우."""


class ExternalSourceValidationError(ExternalResearchError):
    """출처 검증(출처 URL/발행기관/본문 등)이 실패한 경우. 검색 서비스는 이 예외를
    잡아 해당 후보만 제외하고 나머지 검색은 계속 진행한다."""


__all__ = [
    "ExternalResearchError",
    "ExternalResearchValidationError",
    "ExternalCollectionUnavailableError",
    "ExternalEvidenceIndexingError",
    "ExternalEvidenceSearchError",
    "ExternalProviderUnavailableError",
    "ExternalProviderTimeoutError",
    "ExternalSourceValidationError",
]
