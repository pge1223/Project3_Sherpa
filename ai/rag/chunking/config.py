"""
Chunking Configuration Defaults
================================
"""

DEFAULT_CHUNK_SIZE: int = 800
DEFAULT_CHUNK_OVERLAP: int = 120

# 한국어 문단/문장 경계를 우선 고려한 분할 기준 (문자 수 기준).
# 문단(빈 줄) -> 줄바꿈 -> 문장 종결부호(한글은 마침표 앞의 '다/요' 등에 의존하지 않고
# 보편적인 종결부호 자체로 판단) -> 전각 문장부호 -> 공백 -> 강제 문자 단위 분할("").
# RecursiveCharacterTextSplitter는 순서대로 첫 번째로 텍스트에 존재하는 구분자를 사용하므로
# 더 구체적인 구분자를 먼저 두되, 중복되는 하위집합(예: "다. "는 이미 ". "에 포함)은 넣지 않는다.
DEFAULT_SEPARATORS: list[str] = [
    "\n\n",
    "\n",
    ". ", "! ", "? ",
    "。", "！", "？",
    " ",
    "",
]

CHUNKING_VERSION: str = "chunking_v1"

# 목차 판정: MVP는 강한 heading 키워드가 있을 때만 확정한다 (과탐 방지 우선)
TOC_HEADING_KEYWORDS: list[str] = ["목차", "차례", "contents"]

# 구조적 목차 의심(점선/페이지번호로 끝나는 줄 비율) 임계값.
# 이 신호만으로는 절대 TOC로 확정하지 않고 warning 용도로만 사용한다.
TOC_STRUCTURAL_LINE_MATCH_RATIO: float = 0.8

# 의사(pseudo) heading 인식: "□ 접수방법: ..." 형태의 단락을 section_title 후보로 인식.
# 특정 사이트에 하드코딩하지 않고 이 마커 문자 집합만으로 판단한다.
PSEUDO_HEADING_MARKERS: str = "□■◇◆○●"
PSEUDO_HEADING_MAX_TITLE_LENGTH: int = 30

# 목록형 블록 인식: 아래 마커가 반복되면(최소 발생 횟수 이상) 항목 단위로 취급해
# RecursiveCharacterTextSplitter가 항목 중간을 자르지 않도록 한다.
# "-"(줄바꿈 뒤 하이픈), "□", "※", "①"~"⑩"(U+2460~U+2469)
LIST_ITEM_MARKER_PATTERN: str = r"[-□※]|[①-⑩]"
LIST_ITEM_MIN_MARKER_COUNT: int = 2

# 마지막 청크가 이 길이(문자 수) 미만이면 직전 청크와 병합을 시도한다.
# 병합 후 chunk_size를 초과하면 병합하지 않는다.
TAIL_CHUNK_MIN_CHARS: int = 80
