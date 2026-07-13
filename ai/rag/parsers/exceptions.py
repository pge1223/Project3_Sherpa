"""
Custom Exceptions for Document Parsing
======================================
"""


class ParserError(Exception):
    """파싱 중 일반 오류"""
    pass


class EmptyDocumentError(ParserError):
    """빈 문서 예외 (추출할 텍스트가 없는 경우)"""
    pass


class CorruptedDocumentError(ParserError):
    """손상된 문서 예외 (파일을 열거나 파싱할 수 없는 경우)"""
    pass


class UnsupportedFormatError(ParserError):
    """지원하지 않는 파일 형식"""
    pass


class FileSizeLimitExceededError(ParserError):
    """파일 크기 초과 (기본 제한: 20MB)"""
    pass
