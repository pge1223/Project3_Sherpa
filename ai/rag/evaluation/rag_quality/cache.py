# 작성자: 용준/Claude(2026-07-22)
# 목적: judge.py의 LLM 판정 결과를 (prompt, model, prompt_version) 해시로 파일 캐시한다 —
#       같은 입력을 반복 평가할 수 있어야 한다는 요청(7번)을 만족한다. API 키·전체
#       프롬프트 원문은 캐시 파일에 저장하지 않는다(프롬프트 해시만 파일명, 값은 판정
#       결과 JSON만).
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

DEFAULT_CACHE_DIR = Path(__file__).resolve().parent / ".judge_cache"


class JudgeCache:
    def __init__(self, cache_dir: Path | str = DEFAULT_CACHE_DIR, *, enabled: bool = True):
        self.cache_dir = Path(cache_dir)
        self.enabled = enabled
        if self.enabled:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _key(self, prompt: str, model: str, prompt_version: str) -> str:
        digest = hashlib.sha256(f"{model}::{prompt_version}::{prompt}".encode("utf-8")).hexdigest()
        return digest

    def get(self, prompt: str, model: str, prompt_version: str) -> Optional[dict]:
        if not self.enabled:
            return None
        path = self.cache_dir / f"{self._key(prompt, model, prompt_version)}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def set(self, prompt: str, model: str, prompt_version: str, value: dict) -> None:
        if not self.enabled:
            return
        path = self.cache_dir / f"{self._key(prompt, model, prompt_version)}.json"
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
