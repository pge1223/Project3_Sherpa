"""
Smoke Tests for scripts/verify_klawyer_rag_quality.py
==========================================================
KURE/LibreOffice 없이도 스크립트가 안전하게 동작하는지만 확인한다(실제 HWPX 검증은
수동 실행 대상 — README/완료 보고 참고). subprocess로 별도 프로세스에서 실행해
sys.path 부트스트랩이 실제로 동작하는지까지 확인한다.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "verify_klawyer_rag_quality.py"


def _run(args: list[str], timeout: float = 10.0) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=timeout,
    )


class TestScriptCanBeInvokedWithoutPYTHONPATH:
    """repo 루트를 PYTHONPATH에 넣지 않고 `python scripts/...`로 바로 실행해도
    ModuleNotFoundError('ai')가 나지 않아야 한다 — 스크립트 자체의 sys.path 부트스트랩 확인."""

    def test_help_exits_zero_without_heavy_imports(self):
        start = time.monotonic()
        result = _run(["--help"])
        elapsed = time.monotonic() - start

        assert result.returncode == 0
        assert "hwpx_path" in result.stdout
        # KURE/LibreOffice를 로드했다면 수 초~수십 초가 걸린다 — 즉시 종료되는지로 간접 확인.
        assert elapsed < 5.0

    def test_missing_argument_exits_with_usage_error(self):
        result = _run([])
        assert result.returncode == 2
        assert "hwpx_path" in result.stderr

    def test_nonexistent_file_reports_error_and_exits_one(self):
        result = _run(["definitely_does_not_exist.hwpx"])
        assert result.returncode == 1
        assert "찾을 수 없습니다" in result.stdout


class TestScriptModuleImportable:
    def test_module_imports_without_running_main(self):
        """모듈 top-level import에서 ai.rag.* 무거운 의존성을 끌어오지 않는지 확인한다
        (run() 내부에서만 import하므로, 모듈 import 자체는 가벼워야 한다)."""
        import importlib.util

        spec = importlib.util.spec_from_file_location("verify_klawyer_rag_quality", SCRIPT_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        assert hasattr(module, "run")
        assert hasattr(module, "main")
        assert hasattr(module, "_parse_args")
