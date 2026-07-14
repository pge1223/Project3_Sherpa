"""
Keyword Lexicons for Rule-based HTML Content Cleaning
======================================================
사이트마다 표현이 다른 것을 흡수하기 위한 동의어 목록.
새 사이트에서 오탐/누락이 발견되면 원칙적으로 이 파일만 튜닝하고,
html_cleaner.py의 로직은 바꾸지 않는 것을 지향한다.

키 순서가 매치 우선순위에 영향을 주지는 않는다 (첫 매치를 사용하되,
카테고리 간에는 의미상 우열이 없음). 하나의 섹션에서 REMOVE 키워드가
매치되면 KEEP 키워드는 아예 검사하지 않는다 (html_cleaner._classify_section 참고).
"""

# 유지해야 하는 핵심 정보 섹션의 heading/본문 키워드
KEEP_HEADING_KEYWORDS: dict[str, list[str]] = {
    "organizer": ["주최", "주관", "후원"],
    "period": ["모집기간", "접수기간", "응모기간", "신청기간", "공모기간", "행사일정"],
    "eligibility": ["참가자격", "지원자격", "응모자격", "모집대상", "참가대상"],
    "topic": ["공모주제", "공모분야", "공모내용", "주제"],
    "how_to_apply": ["제출방법", "응모방법", "신청방법", "접수방법", "참가방법"],
    "submission_format": ["제출형식", "제출양식", "작성요령"],
    "evaluation": ["심사기준", "심사방법", "평가기준", "심사위원"],
    "awards": ["시상내역", "시상", "상금", "지원내용", "지원사항", "혜택"],
    "contact": ["문의처", "문의", "운영사무국", "담당자", "연락처"],
    "notice": ["유의사항", "참고사항", "기타사항", "안내사항"],
    "overview": ["공모요강", "모집요강", "공고내용", "사업개요"],
}

# 제거해야 하는 노이즈 섹션의 heading/본문 키워드
REMOVE_HEADING_KEYWORDS: dict[str, list[str]] = {
    "nav_menu": ["전체메뉴", "카테고리", "quick menu", "퀵메뉴", "바로가기", "사이트맵"],
    "login_signup": ["로그인", "회원가입", "마이페이지", "아이디 찾기", "비밀번호 찾기"],
    "advertisement": ["광고", "배너", "스폰서"],
    "recommended_content": [
        "함께 보면 좋은", "관련 공모전", "이런 공모전", "인기 공모전", "최신 공모전", "추천 공모전", "추천",
    ],
    "newsletter": ["뉴스레터", "구독하기", "이메일 수신", "알림 신청", "알림받기"],
    "company_info_footer": [
        "회사소개", "사업자등록번호", "대표자", "통신판매업", "이용약관",
        "개인정보처리방침", "청소년보호정책", "copyright",
    ],
}

# KEEP 섹션 내부에 개별적으로 섞여 들어온 상용구 블록 판정
BLOCK_LEVEL_BOILERPLATE_MARKERS: list[str] = [
    "이용약관", "개인정보처리방침", "사업자등록번호", "통신판매업",
    "청소년보호정책", "copyright", "ⓒ", "all rights reserved",
]
BLOCK_LEVEL_BOILERPLATE_MAX_LENGTH = 80  # 상용구 블록은 대체로 짧음 -> 긴 블록은 우연히 문구가 섞였을 뿐일 수 있어 제외

# heading 없는 preamble 섹션이 "메뉴형 나열"인지 판정하는 구조적 임계값
STRUCTURAL_NOISE_MAX_BLOCKS = 6          # 이보다 블록 수가 많으면 메뉴로 보지 않음(본문일 가능성)
STRUCTURAL_NOISE_MAX_BLOCK_LENGTH = 12   # 블록 중 하나라도 이보다 길면 메뉴 항목으로 보지 않음

# preamble(첫 heading 이전) 영역에서 메뉴/카테고리로 자주 쓰이는 표현.
# 여러 메뉴 항목이 하나의 블록에 붙어서 추출된 사이트를 잡기 위한 보조 신호로 사용한다.
PREAMBLE_MENU_KEYWORDS: list[str] = [
    "공모전", "대외활동", "이벤트", "로그인", "회원가입",
    "카테고리", "배너광고", "무료 등록", "메뉴", "마이페이지",
]

# preamble 보호(제거하지 않음) 판정 전용 키워드.
# KEEP_HEADING_KEYWORDS보다 훨씬 좁게 잡는다 — "시상"처럼 짧고 일반적인 KEEP 키워드가
# "시상식 갤러리" 같은 메뉴 라벨 안에 우연히 포함되어 preamble 메뉴 제거를 막는 오탐을 방지하기 위함.
# "공모전"/"대외활동"/"이벤트"/"공고"/"사업"/"홈페이지"처럼 메뉴에도 흔히 쓰이는 일반 단어는 제외한다.
PREAMBLE_STRONG_CORE_KEYWORDS: list[str] = [
    "접수기간", "모집기간", "참가자격", "지원자격", "공모주제",
    "제출방법", "신청방법", "심사기준", "시상내역", "지원내용",
    "주최", "주관", "문의처",
]

# preamble 메뉴 판정에 쓰는 신호 개수 임계값 (아래 여러 신호 중 최소 이만큼 겹쳐야 제거)
PREAMBLE_MENU_MIN_SIGNALS = 2
# 구분자(-, /, 줄바꿈)로 나눴을 때 "짧은 항목"으로 볼 최대 길이 및 최소 개수
PREAMBLE_DELIMITED_ITEM_MAX_LENGTH = STRUCTURAL_NOISE_MAX_BLOCK_LENGTH
PREAMBLE_DELIMITED_ITEM_MIN_COUNT = 4

# fallback(안전 모드) 트리거 조건
MIN_RETENTION_RATIO = 0.05
MIN_MEANINGFUL_ORIGINAL_TEXT_LENGTH = 200
