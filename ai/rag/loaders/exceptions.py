"""
Custom Exceptions for URL-based Document Loading
=================================================
"""


class LoaderError(Exception):
    """URL 로더 최상위 예외"""
    pass


class InvalidUrlError(LoaderError):
    """URL 형식/스킴이 유효하지 않음 (http/https 외)"""
    pass


class BlockedUrlError(LoaderError):
    """SSRF 방지 대상 URL (사설/루프백/링크로컬/예약/멀티캐스트 IP 등)"""
    pass


class UrlFetchError(LoaderError):
    """네트워크 요청 실패 (타임아웃, 연결 오류, HTTP 오류 등)"""
    pass


class TooManyRedirectsError(LoaderError):
    """리다이렉트 허용 횟수 초과"""
    pass


class DownloadSizeLimitExceededError(LoaderError):
    """다운로드 크기가 제한을 초과함 (개별 파일 또는 URL 1건 전체 누적)"""
    pass


class ContentTypeMismatchError(LoaderError):
    """선언된 형식(확장자/Content-Type)과 실제 파일 시그니처가 일치하지 않음"""
    pass
