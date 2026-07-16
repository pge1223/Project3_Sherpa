"""
Custom Exceptions for Document Conversion (HWP/HWPX -> PDF)
=================================================================
각 예외는 개발자용 상세 메시지(Exception 인자)와 별개로 프론트에 그대로 노출해도 되는
`user_message`를 갖는다. `user_message`에는 서버 내부 경로, subprocess stderr, 명령어
등 민감한 정보를 포함하지 않는다.
"""

from typing import Optional


class DocumentConversionError(Exception):
    """HWP/HWPX 변환 관련 예외의 공통 베이스."""

    user_message: str = "문서를 변환하지 못했습니다."

    def __init__(self, message: str, *, user_message: Optional[str] = None):
        super().__init__(message)
        if user_message is not None:
            self.user_message = user_message


class ConverterUnavailableError(DocumentConversionError):
    """변환 도구가 설치되어 있지 않거나 비활성화된 경우."""

    user_message = "현재 서버에서 HWP/HWPX 문서 변환을 사용할 수 없습니다. PDF로 변환한 뒤 다시 업로드해 주세요."


class UnsupportedConversionFormatError(DocumentConversionError):
    """변환 대상이 아닌 확장자(PDF/DOCX/PPTX 등)를 변환기에 넘긴 경우."""

    user_message = "지원하지 않는 문서 형식입니다."


class ConversionTimeoutError(DocumentConversionError):
    """설정된 timeout_seconds 안에 변환이 끝나지 않은 경우."""

    user_message = "문서 변환 시간이 초과되었습니다. 파일 크기를 확인하거나 PDF로 변환한 뒤 다시 업로드해 주세요."


class ConversionProcessError(DocumentConversionError):
    """변환 프로세스가 0이 아닌 종료 코드로 끝난 경우."""

    user_message = "HWP/HWPX 문서를 PDF로 변환하지 못했습니다. 파일이 손상되었거나 지원하지 않는 문서 버전일 수 있습니다."


class ConvertedFileNotFoundError(DocumentConversionError):
    """변환 프로세스는 성공했지만 출력 PDF가 생성되지 않은 경우."""

    user_message = "HWP/HWPX 문서를 PDF로 변환하지 못했습니다. 파일이 손상되었거나 지원하지 않는 문서 버전일 수 있습니다."


class InvalidConvertedPdfError(DocumentConversionError):
    """출력 PDF가 0바이트이거나 PDF 시그니처를 만족하지 않는 경우."""

    user_message = "PDF 변환은 완료됐지만 문서 내용을 읽지 못했습니다. 암호화되었거나 손상된 문서인지 확인해 주세요."


class InvalidSourceFileError(DocumentConversionError):
    """원본 파일이 없거나, 비어 있거나, 확장자와 실제 형식이 일치하지 않는 경우."""

    user_message = "문서 파일이 손상되었거나 올바른 형식이 아닙니다."


class SourceFileTooLargeError(DocumentConversionError):
    """원본 파일이 max_file_size_bytes를 초과하는 경우."""

    user_message = "파일 크기가 제한을 초과합니다."


__all__ = [
    "DocumentConversionError",
    "ConverterUnavailableError",
    "UnsupportedConversionFormatError",
    "ConversionTimeoutError",
    "ConversionProcessError",
    "ConvertedFileNotFoundError",
    "InvalidConvertedPdfError",
    "InvalidSourceFileError",
    "SourceFileTooLargeError",
]
