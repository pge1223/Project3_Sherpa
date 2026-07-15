import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jose import jwt

# backend/ 를 sys.path에 추가해 `from app.main import app`이 되도록 한다
# (app.main 자신이 레포 루트를 추가하는 로직은 그 이후에 실행됨).
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.main import app
from app.config import settings


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_header() -> dict:
    token = jwt.encode({"sub": "tester@example.com"}, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return {"authorization": f"Bearer {token}"}
