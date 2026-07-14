"""
Base OCR Abstract Class
=======================
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Protocol


@dataclass
class OCRResult:
    """OCR 처리 결과"""
    text: str
    confidence: float
    bounding_boxes: list[dict] | None = None
    language: str | None = None


class BaseOCR(ABC):
    """
    OCR 엔진 기본 클래스

    모든 OCR 구현체는 이 클래스를 상속받아 구현
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """OCR 엔진 이름 반환"""
        pass

    @property
    def supported_languages(self) -> list[str]:
        """지원하는 언어 목록 (기본값: 한국어, 영어)"""
        return ["ko", "en"]

    @abstractmethod
    def is_available(self) -> bool:
        """
        OCR 엔진 사용 가능 여부 확인

        True: OCR可以使用
        False: OCR使用不可 (환경설정 미비, 모델 미설치 등)
        """
        pass

    @abstractmethod
    def extract_text(self, image_path: str) -> OCRResult:
        """
        이미지에서 텍스트 추출

        Args:
            image_path: 이미지 파일 경로

        Returns:
            OCRResult: 추출된 텍스트 및 신뢰도
        """
        pass

    @abstractmethod
    def extract_text_from_bytes(self, image_bytes: bytes) -> OCRResult:
        """
        이미지 바이트에서 텍스트 추출

        Args:
            image_bytes: 이미지 바이트 데이터

        Returns:
            OCRResult: 추출된 텍스트 및 신뢰도
        """
        pass

    def extract_text_batch(self, image_paths: list[str]) -> list[OCRResult]:
        """
        여러 이미지에서 배치로 텍스트 추출

        Args:
            image_paths: 이미지 파일 경로 목록

        Returns:
            list[OCRResult]: 각 이미지의 OCR 결과 목록
        """
        return [self.extract_text(path) for path in image_paths]
