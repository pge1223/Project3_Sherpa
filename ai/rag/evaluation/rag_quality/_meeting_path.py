# 작성자: 용준/Claude(2026-07-22)
# 목적: ai/meeting은 __init__.py가 없는 비-패키지 디렉터리라 ai/meeting을 sys.path에 직접
#       올려야 그 안의 graph/prompts가 최상위 모듈로 import된다 — 이 저장소 전역에서 이미
#       쓰는 관례(backend/app/api/routes/ideation_conversation_preview.py 등)를 그대로
#       따른다. 이 모듈은 그 sys.path 등록을 한 곳에서만 하도록 모은 것뿐이고, 새 로직은
#       없다.
from __future__ import annotations

import sys
from pathlib import Path

_MEETING_DIR = Path(__file__).resolve().parents[3] / "meeting"  # ai/meeting


def ensure_meeting_on_path() -> None:
    if str(_MEETING_DIR) not in sys.path:
        sys.path.insert(0, str(_MEETING_DIR))
