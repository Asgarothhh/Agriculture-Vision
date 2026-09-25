"""Pytest fixtures: real PostgreSQL + Redis, mocked GPU weights."""

from __future__ import annotations

import io
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image as PILImage

from app.ml_service.schemas import InferenceFeature, InferenceResponse

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session", autouse=True)
def _seed_reference_and_demo():
    from app.core.seed import seed, seed_demo

    seed()
    seed_demo()


@pytest.fixture(autouse=True)
def _isolate_dzz_sessions(tmp_path, monkeypatch):
    from app.dzz_service import sessions

    path = tmp_path / "dzz-sessions.enc"
    monkeypatch.setattr(sessions, "sessions_path", lambda: path)
    sessions.reset_sessions()
    yield
    sessions.reset_sessions()


@pytest.fixture(autouse=True)
def _disable_auth_rate_limit():
    from app.core.ratelimit import limiter

    limiter.enabled = False
    yield
    limiter.enabled = True


@pytest.fixture(autouse=True)
def _stub_ml_load(monkeypatch):
    from app.ml_service.runtime import runtime

    def fake_load():
        runtime._loaded = {"yolo_seg_26": True, "segformer": True}
        runtime._paths = {
            "yolo_seg_26": str(ROOT / "config" / "yolo_best.pt"),
            "segformer": str(ROOT / "config" / "segformer_best.pt"),
        }
        runtime._errors = {}
        return runtime.health()

    monkeypatch.setattr("app.ml_service.runtime.load_models", fake_load)
    monkeypatch.setattr(runtime, "load_models", fake_load)
    fake_load()
    yield
    runtime.reset()


@pytest.fixture
def client(_stub_ml_load) -> TestClient:
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db_session():
    from app.core.database import SyncSessionLocal

    session = SyncSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def demo_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "agronom@agrovision.dev", "password": "ValidPass1!", "remember_me": False},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def operator_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "operator@agrovision.dev", "password": "ValidPass1!", "remember_me": False},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def auth_headers(client: TestClient) -> dict[str, str]:
    email = f"test-{uuid.uuid4().hex[:10]}@example.com"
    payload = {
        "first_name": "Тест",
        "last_name": "Пользователь",
        "email": email,
        "organization": "КФХ",
        "role": "Агроном",
        "password": "ValidPass1!",
        "password_repeat": "ValidPass1!",
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def tiny_png() -> bytes:
    buf = io.BytesIO()
    PILImage.new("RGB", (8, 8), color=(34, 139, 34)).save(buf, format="PNG")
    return buf.getvalue()


def empty_inference(*_args, **_kwargs) -> InferenceResponse:
    return InferenceResponse(model="segformer", polygons=[], points=[])


def sample_inference(*_args, **_kwargs) -> InferenceResponse:
    ring = [[[27.45, 53.88], [27.48, 53.88], [27.48, 53.90], [27.45, 53.90], [27.45, 53.88]]]
    return InferenceResponse(
        model="segformer",
        polygons=[
            InferenceFeature(
                class_id=2,
                confidence=0.82,
                geometry={"type": "Polygon", "coordinates": ring},
                crop_probabilities={10: 0.7, 11: 0.3},
            )
        ],
        points=[
            InferenceFeature(
                class_id=5,
                confidence=0.91,
                geometry={"type": "Point", "coordinates": [27.46, 53.89]},
                radius_approx=2.5,
                area_approx=19.6,
            )
        ],
    )
