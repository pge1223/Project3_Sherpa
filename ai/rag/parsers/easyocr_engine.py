"""
EasyOCR Implementation
======================
"""

import io
import warnings
from pathlib import Path

import easyocr

from ai.rag.parsers.base_ocr import BaseOCR, OCRResult


class OCRInitializationError(Exception):
    """EasyOCR 초기화 실패 예외"""
    pass


class EasyOCR(BaseOCR):
    """
    EasyOCR 기반 OCR 구현체

    한국어와 영어 텍스트 인식을 지원합니다.
    GPU 가속을 자동으로 감지하여 사용합니다.
    """

    def __init__(
        self,
        languages: list[str] | None = None,
        gpu: bool | None = None,
        model_storage_directory: str | None = None,
        download_enabled: bool = True,
        raise_on_init_error: bool = False,
    ):
        """
        EasyOCR 초기화

        Args:
            languages: 인식할 언어 목록 (기본값: ['ko', 'en'])
            gpu: GPU 사용 여부 (None: 자동 감지)
            model_storage_directory: 모델 저장 디렉토리
            download_enabled: 모델 자동 다운로드 허용 여부
            raise_on_init_error: 초기화 실패 시 예외 발생 여부
        """
        self._languages = languages or ["ko", "en"]
        self._gpu = gpu
        self._model_storage_directory = model_storage_directory
        self._download_enabled = download_enabled
        self._raise_on_init_error = raise_on_init_error
        self._reader: easyocr.Reader | None = None
        self._init_error: str | None = None

    @property
    def name(self) -> str:
        return "EasyOCR"

    @property
    def supported_languages(self) -> list[str]:
        return ["ko", "en", "ja", "zh"]

    def _get_reader(self) -> easyocr.Reader:
        """
        Lazy initialization of EasyOCR Reader.

        Returns:
            easyocr.Reader: 초기화된 Reader 객체

        Raises:
            OCRInitializationError: 초기화 실패 시 (raise_on_init_error=True인 경우)
        """
        if self._reader is None:
            if self._init_error is not None:
                if self._raise_on_init_error:
                    raise OCRInitializationError(self._init_error)
                return None  # type: ignore

            try:
                self._reader = easyocr.Reader(
                    lang_list=self._languages,
                    gpu=self._gpu if self._gpu is not None else True,
                    model_storage_directory=self._model_storage_directory,
                    download_enabled=self._download_enabled,
                )
            except Exception as e:
                self._init_error = f"EasyOCR Reader 초기화 실패: {e}"
                if self._raise_on_init_error:
                    raise OCRInitializationError(self._init_error)
                warnings.warn(self._init_error)
                return None  # type: ignore

        return self._reader

    def is_available(self) -> bool:
        """
        EasyOCR 사용 가능 여부 확인.

        Reader 초기화까지 시도하고 성공하면 True 반환.
        """
        try:
            # 먼저 easyocr 모듈 import 확인
            import easyocr
            reader = self._get_reader()
            return reader is not None
        except (ImportError, OCRInitializationError):
            return False

    def extract_text(self, image_path: str | Path) -> OCRResult:
        """
        이미지 파일에서 텍스트 추출

        Args:
            image_path: 이미지 파일 경로

        Returns:
            OCRResult: 추출된 텍스트 및 메타데이터
        """
        reader = self._get_reader()
        if reader is None:
            warnings.warn("EasyOCR Reader가 초기화되지 않았습니다.")
            return OCRResult(text="", confidence=0.0)

        results = reader.readtext(str(image_path))

        if not results:
            return OCRResult(text="", confidence=0.0)

        # 결과聚合
        full_text_parts = []
        confidences = []
        bounding_boxes = []

        for detection in results:
            bbox, text, confidence = detection
            if text and text.strip():
                full_text_parts.append(text.strip())
                confidences.append(confidence)
                bounding_boxes.append({
                    "bbox": bbox,
                    "text": text.strip(),
                    "confidence": confidence,
                })

        # 평균 신뢰도 계산
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

        return OCRResult(
            text=" ".join(full_text_parts),
            confidence=avg_confidence,
            bounding_boxes=bounding_boxes,
            language=",".join(self._languages),
        )

    def extract_text_from_bytes(self, image_bytes: bytes) -> OCRResult:
        """
        이미지 바이트 데이터에서 텍스트 추출

        Args:
            image_bytes: 이미지 바이트 데이터

        Returns:
            OCRResult: 추출된 텍스트 및 메타데이터
        """
        import numpy as np
        from PIL import Image

        reader = self._get_reader()
        if reader is None:
            warnings.warn("EasyOCR Reader가 초기화되지 않았습니다.")
            return OCRResult(text="", confidence=0.0)

        # 바이트를 이미지로 변환
        image = Image.open(io.BytesIO(image_bytes))
        image_array = np.array(image)

        results = reader.readtext(image_array)

        if not results:
            return OCRResult(text="", confidence=0.0)

        # 결과聚合
        full_text_parts = []
        confidences = []
        bounding_boxes = []

        for detection in results:
            bbox, text, confidence = detection
            if text and text.strip():
                full_text_parts.append(text.strip())
                confidences.append(confidence)
                bounding_boxes.append({
                    "bbox": bbox,
                    "text": text.strip(),
                    "confidence": confidence,
                })

        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

        return OCRResult(
            text=" ".join(full_text_parts),
            confidence=avg_confidence,
            bounding_boxes=bounding_boxes,
            language=",".join(self._languages),
        )
