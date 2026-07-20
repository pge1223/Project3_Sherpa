"""
GET /health의 HWP capability 응답을 검증한다. 실제 LibreOffice/Java 유무와 무관하게
결정적으로 동작하도록 startup 진단(run_hwp_diagnostics)을 mock한다.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from ai.rag.converters.diagnostics import HwpDiagnosticsResult
from app.main import app


def _client_with_diagnostics(result: HwpDiagnosticsResult) -> TestClient:
    with patch("app.main.run_hwp_diagnostics", return_value=result):
        client = TestClient(app)
        with client:
            yield client


@pytest.fixture
def ready_client():
    result = HwpDiagnosticsResult(
        enabled=True,
        available=True,
        libreoffice=True,
        h2orestart=True,
        java=True,
        temp_dir_writable=True,
        reason=None,
    )
    yield from _client_with_diagnostics(result)


@pytest.fixture
def degraded_client():
    result = HwpDiagnosticsResult(
        enabled=True,
        available=False,
        libreoffice=True,
        h2orestart=False,
        java=True,
        temp_dir_writable=True,
        reason="H2Orestart extension is not registered for the backend runtime user",
    )
    yield from _client_with_diagnostics(result)


@pytest.fixture
def disabled_client():
    result = HwpDiagnosticsResult(
        enabled=False,
        available=False,
        libreoffice=False,
        h2orestart=False,
        java=False,
        temp_dir_writable=False,
        reason="HWP conversion is disabled",
    )
    yield from _client_with_diagnostics(result)


class TestHealthReady:
    def test_status_ok_when_hwp_available(self, ready_client):
        response = ready_client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["capabilities"]["hwp_conversion"] == {
            "enabled": True,
            "available": True,
            "libreoffice": True,
            "h2orestart": True,
            "java": True,
            "temp_dir_writable": True,
            "reason": None,
        }


class TestHealthDegraded:
    def test_status_degraded_when_enabled_but_unavailable(self, degraded_client):
        response = degraded_client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "degraded"
        hwp = body["capabilities"]["hwp_conversion"]
        assert hwp["enabled"] is True
        assert hwp["available"] is False
        assert hwp["h2orestart"] is False
        assert hwp["reason"] == "H2Orestart extension is not registered for the backend runtime user"


class TestHealthDisabled:
    def test_status_stays_ok_when_intentionally_disabled(self, disabled_client):
        response = disabled_client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        hwp = body["capabilities"]["hwp_conversion"]
        assert hwp["enabled"] is False
        assert hwp["available"] is False
        assert hwp["reason"] == "HWP conversion is disabled"


class TestHealthNoResponseLeaksSensitiveInfo:
    def test_no_absolute_paths_or_raw_output_in_response(self, ready_client):
        response = ready_client.get("/health")
        body_text = response.text
        assert "Program Files" not in body_text
        assert "soffice.exe" not in body_text
        assert "C:\\" not in body_text


class TestHealthDiagnosticsFailSafe:
    def test_status_degraded_when_startup_diagnostics_call_itself_raises(self):
        """run_hwp_diagnostics() 호출 자체가 (그 내부 방어를 뚫고) 예외를 던지는
        최악의 경우에도, main.py의 startup 핸들러는 서버 기동을 막지 않고 fail-safe로
        enabled=True/available=False를 기록해야 한다 — enabled=False로 위장해
        status="ok"가 되면 실제 장애가 숨겨진다."""
        if hasattr(app.state, "hwp_diagnostics"):
            del app.state.hwp_diagnostics

        with patch("app.main.run_hwp_diagnostics", side_effect=RuntimeError("boom")):
            with TestClient(app) as client:  # startup 이벤트가 여기서 실행된다
                response = client.get("/health")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "degraded"
        hwp = body["capabilities"]["hwp_conversion"]
        assert hwp["enabled"] is True
        assert hwp["available"] is False
        assert "boom" not in response.text


class TestHealthWithoutStartupEvent:
    def test_safe_default_when_startup_never_ran(self):
        """TestClient(app)를 컨텍스트 매니저 없이 쓰면 startup 이벤트가 실행되지 않는다 —
        app.state.hwp_diagnostics가 없는 상태에서도 /health가 죽지 않고 안전한 기본값을
        반환해야 한다. app은 테스트 세션 내내 재사용되는 싱글턴이라, 다른 테스트가 이미
        startup을 거쳐 app.state를 채워놨을 수 있으므로 명시적으로 지워 시뮬레이션한다."""
        if hasattr(app.state, "hwp_diagnostics"):
            del app.state.hwp_diagnostics

        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["capabilities"]["hwp_conversion"]["enabled"] is False
        assert body["capabilities"]["hwp_conversion"]["available"] is False
