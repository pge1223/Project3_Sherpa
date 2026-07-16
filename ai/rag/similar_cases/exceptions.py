"""
Custom Exceptions for Similar Case Search (RAG-006)
=========================================================
"""


class SimilarCaseError(Exception):
    """유사 사례 검색 모듈 예외의 공통 베이스."""


class SimilarCaseValidationError(SimilarCaseError):
    """검색 요청 또는 사례 데이터가 필수 조건(빈 값, NaN/Inf, 출처 누락 등)을 만족하지 않는 경우.

    Pydantic v2는 필드/모델 validator에서 ValueError/TypeError/AssertionError가 아닌
    예외를 그대로(감싸지 않고) 전파하므로, 이 예외를 validator 안에서 raise해도
    pydantic.ValidationError로 감싸이지 않고 이 타입 그대로 호출자에게 전달된다.
    """


class SimilarCaseCollectionUnavailableError(SimilarCaseError):
    """사례 전용 Chroma 컬렉션에 접근할 수 없거나 기존 설정과 충돌하는 경우."""


class SimilarCaseIndexingError(SimilarCaseError):
    """사례 색인 중 복구 불가능한 오류가 발생한 경우(개별 사례 스킵과는 별개)."""


class SimilarCaseSearchError(SimilarCaseError):
    """검색 자체(임베딩/Chroma 질의)가 실패한 경우. 결과가 0건인 것은 오류가 아니다."""


class SimilarCaseComparisonError(SimilarCaseError):
    """공통점/차이점/유사 이유 생성이 실패한 경우. 이 예외는 서비스 내부에서만 사용되며,
    검색 결과 자체를 실패시키지 않기 위해 search_service가 이 예외를 잡아 fallback 처리한다."""


__all__ = [
    "SimilarCaseError",
    "SimilarCaseValidationError",
    "SimilarCaseCollectionUnavailableError",
    "SimilarCaseIndexingError",
    "SimilarCaseSearchError",
    "SimilarCaseComparisonError",
]
