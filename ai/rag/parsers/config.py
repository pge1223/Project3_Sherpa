"""
Scanned PDF Detection Configuration
====================================
"""

# 페이지당 최소 텍스트 길이 (이 미만이면 해당 페이지를 스캔으로 판단)
MIN_TEXT_LENGTH_PER_PAGE: int = 10

# 스캔 PDF 판정 비율 (전체 페이지 중 이 비율 이상이 스캔 페이지면 전체 스캔으로 판단)
SCAN_PAGE_RATIO_THRESHOLD: float = 0.7  # 70%


def get_scan_detection_config() -> dict:
    """스캔 PDF 탐지 설정 반환"""
    return {
        "min_text_length_per_page": MIN_TEXT_LENGTH_PER_PAGE,
        "scan_page_ratio_threshold": SCAN_PAGE_RATIO_THRESHOLD,
    }


def update_scan_detection_config(
    min_text_length: int | None = None,
    ratio_threshold: float | None = None,
) -> dict:
    """
    스캔 PDF 탐지 설정 업데이트 (런타임 변경용)
    """
    global MIN_TEXT_LENGTH_PER_PAGE, SCAN_PAGE_RATIO_THRESHOLD

    if min_text_length is not None:
        MIN_TEXT_LENGTH_PER_PAGE = min_text_length
    if ratio_threshold is not None:
        SCAN_PAGE_RATIO_THRESHOLD = ratio_threshold

    return get_scan_detection_config()
