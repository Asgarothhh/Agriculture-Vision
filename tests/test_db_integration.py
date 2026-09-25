from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import func, select

from app.core.seed import DEMO_PASSWORD
from app.dzz_service.models import DzzConnection
from app.layers_service.models import Folder, Layer, LayerObject
from app.ml_service.models import ModelRegistry, ObjectClass, PointObject, PolygonObject
from app.tasks_service.models import Image, ProcessingTask
from app.users_service.models import User
from tests.conftest import sample_inference, tiny_png


def _user(db_session, email: str) -> User:
    user = db_session.scalar(select(User).where(User.username == email))
    assert user is not None, email
    return user


def _patch_eager_infer(monkeypatch, infer=sample_inference):
    def fake_upload(key, data, content_type="application/octet-stream"):
        return key

    def fake_send(name, args=None, kwargs=None, **_extra):
        from app.tasks_service.workers import run_inference

        run_inference(*(args or []), **(kwargs or {}))

    monkeypatch.setattr("app.ml_service.runtime.infer_sync", infer)
    monkeypatch.setattr("app.tasks_service.workers.infer_sync", infer)
    monkeypatch.setattr("app.tasks_service.service.upload_bytes", fake_upload)
    monkeypatch.setattr("app.tasks_service.workers.download_bytes", lambda key: tiny_png())
    monkeypatch.setattr("app.core.celery_app.celery_app.send_task", fake_send)


def test_seed_demo_rows_in_postgres(db_session):
    emails = {
        "admin@agrovision.dev",
        "agronom@agrovision.dev",
        "operator@agrovision.dev",
    }
    found = set(db_session.scalars(select(User.username).where(User.username.in_(emails))))
    assert found == emails
    assert db_session.scalar(select(func.count()).select_from(ObjectClass)) >= 6
    assert db_session.scalar(select(func.count()).select_from(ModelRegistry)) >= 2

    agronom = _user(db_session, "agronom@agrovision.dev")
    auto_layers = db_session.scalars(
        select(Layer).where(Layer.user_id == agronom.id, Layer.kind == "auto")
    ).all()
    assert len(auto_layers) >= 6
    objects = db_session.scalars(
        select(LayerObject).join(Layer).where(Layer.user_id == agronom.id)
    ).all()
    assert any(not item.is_point for item in objects)
    assert any(item.is_point for item in objects)
    statuses = set(
        db_session.scalars(select(ProcessingTask.status).where(ProcessingTask.user_id == agronom.id))
    )
    assert {"PENDING", "FAILED", "COMPLETED"} <= statuses
    assert db_session.scalar(select(func.count()).select_from(PolygonObject)) >= 1
    assert db_session.scalar(select(func.count()).select_from(PointObject)) >= 1
    dzz = db_session.scalar(select(DzzConnection).where(DzzConnection.user_id == agronom.id))
    assert dzz is not None
    assert dzz.is_active is False


def test_demo_login_me_activity_and_isolation(client, demo_headers, operator_headers, db_session):
    me = client.get("/api/v1/users/me", headers=demo_headers)
    assert me.status_code == 200
    assert me.json()["email"] == "agronom@agrovision.dev"
    assert me.json()["role"] == "Агроном"

    activity = client.get("/api/v1/activity/", headers=demo_headers)
    assert activity.status_code == 200
    assert activity.json()["items"]

    agronom_layers = client.get("/api/v1/layers/", headers=demo_headers)
    assert agronom_layers.status_code == 200
    demo_names = {item["name"] for item in agronom_layers.json()}
    assert "Демо поле" in demo_names

    operator_layers = client.get("/api/v1/layers/", headers=operator_headers)
    assert operator_layers.status_code == 200
    assert "Демо поле" not in {item["name"] for item in operator_layers.json()}

    agronom = _user(db_session, "agronom@agrovision.dev")
    db_session.expire_all()
    assert db_session.get(User, agronom.id) is not None


def test_layer_folder_object_roundtrip(client, demo_headers, db_session):
    created = client.post(
        "/api/v1/layers/",
        headers=demo_headers,
        json={"name": "Интеграционный слой", "color": "#123456"},
    )
    assert created.status_code == 200, created.text
    layer_id = created.json()["id"]
    db_session.expire_all()
    assert db_session.get(Layer, uuid.UUID(str(layer_id))) is not None

    patched = client.patch(
        f"/api/v1/layers/{layer_id}",
        headers=demo_headers,
        json={"name": "Слой переименован"},
    )
    assert patched.status_code == 200
    db_session.expire_all()
    assert db_session.get(Layer, uuid.UUID(str(layer_id))).name == "Слой переименован"

    folder = client.post("/api/v1/folders/", headers=demo_headers, json={"name": "Папка теста"})
    assert folder.status_code == 200
    folder_id = folder.json()["id"]
    moved = client.post(
        f"/api/v1/folders/{folder_id}/items",
        headers=demo_headers,
        json={"layer_id": layer_id},
    )
    assert moved.status_code == 200
    db_session.expire_all()
    assert db_session.get(Layer, uuid.UUID(str(layer_id))).folder_id == uuid.UUID(str(folder_id))

    geom = {"type": "Polygon", "coordinates": [[[27.0, 53.0], [27.1, 53.0], [27.1, 53.1], [27.0, 53.0]]]}
    obj1 = client.post(
        f"/api/v1/layers/{layer_id}/objects",
        headers=demo_headers,
        json={"name": "А", "geom": geom, "origin": "manual"},
    )
    obj2 = client.post(
        f"/api/v1/layers/{layer_id}/objects",
        headers=demo_headers,
        json={"name": "Б", "geom": geom, "origin": "manual"},
    )
    assert obj1.status_code == 200, obj1.text
    assert obj2.status_code == 200, obj2.text
    db_session.expire_all()
    assert db_session.get(LayerObject, uuid.UUID(str(obj1.json()["id"]))) is not None

    merged = client.post(
        "/api/v1/objects/merge",
        headers=demo_headers,
        json={"object_ids": [obj1.json()["id"], obj2.json()["id"]]},
    )
    assert merged.status_code == 200, merged.text

    other = client.post(
        "/api/v1/layers/",
        headers=demo_headers,
        json={"name": "Чужой слой", "color": "#00FF00"},
    )
    obj3 = client.post(
        f"/api/v1/layers/{other.json()['id']}/objects",
        headers=demo_headers,
        json={"name": "В", "geom": geom, "origin": "manual"},
    )
    conflict = client.post(
        "/api/v1/objects/merge",
        headers=demo_headers,
        json={"object_ids": [merged.json()["id"], obj3.json()["id"]]},
    )
    assert conflict.status_code == 409

    deleted = client.delete(f"/api/v1/layers/{layer_id}", headers=demo_headers)
    assert deleted.status_code == 200
    db_session.expire_all()
    assert db_session.get(Layer, uuid.UUID(str(layer_id))) is None

    folder_del = client.delete(f"/api/v1/folders/{folder_id}", headers=demo_headers)
    assert folder_del.status_code == 200
    db_session.expire_all()
    assert db_session.get(Folder, uuid.UUID(str(folder_id))) is None


def test_cannot_delete_auto_layer(client, demo_headers):
    listed = client.get("/api/v1/layers/", headers=demo_headers)
    auto = next(item for item in listed.json() if item["kind"] == "auto")
    denied = client.delete(f"/api/v1/layers/{auto['id']}", headers=demo_headers)
    assert denied.status_code == 403


def test_import_export_persists(client, demo_headers, db_session):
    before = db_session.scalar(select(func.count()).select_from(LayerObject)) or 0
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [27.51, 53.91]},
                "properties": {"name": "Импорт точка"},
            }
        ],
    }
    imported = client.post(
        "/api/v1/layers/import",
        headers=demo_headers,
        files={"file": ("import.geojson", json.dumps(geojson).encode("utf-8"), "application/geo+json")},
    )
    assert imported.status_code == 200, imported.text
    db_session.expire_all()
    after = db_session.scalar(select(func.count()).select_from(LayerObject)) or 0
    assert after >= before + 1

    geo = client.post("/api/v1/layers/export", headers=demo_headers, json={"format": "geojson"})
    assert geo.status_code == 200
    kml = client.post("/api/v1/layers/export", headers=demo_headers, json={"format": "kml"})
    assert kml.status_code == 200
    assert kml.headers["content-type"].startswith("application/") or "xml" in kml.headers["content-type"]


def test_task_infer_writes_geometry_and_to_layers(client, demo_headers, db_session, monkeypatch):
    _patch_eager_infer(monkeypatch)
    agronom = _user(db_session, "agronom@agrovision.dev")
    auto_before = db_session.scalar(
        select(func.count())
        .select_from(LayerObject)
        .join(Layer, LayerObject.layer_id == Layer.id)
        .where(Layer.user_id == agronom.id, LayerObject.origin == "auto")
    ) or 0

    created = client.post(
        "/api/v1/tasks/",
        headers=demo_headers,
        files={"file": ("field.png", tiny_png(), "image/png")},
        data={"model": "segformer", "confidence": "0.5"},
    )
    assert created.status_code == 200, created.text
    task_id = uuid.UUID(str(created.json()["task_id"]))

    db_session.expire_all()
    task = db_session.get(ProcessingTask, task_id)
    assert task is not None
    assert task.status == "COMPLETED"
    image = db_session.scalar(select(Image).where(Image.task_id == task_id))
    assert image is not None
    assert db_session.scalar(select(func.count()).select_from(PolygonObject).where(PolygonObject.image_id == image.id)) >= 1
    assert db_session.scalar(select(func.count()).select_from(PointObject).where(PointObject.image_id == image.id)) >= 1

    result = client.get(f"/api/v1/tasks/{task_id}/result", headers=demo_headers)
    assert result.status_code == 200
    assert result.json()["type"] == "FeatureCollection"

    published = client.post(f"/api/v1/tasks/{task_id}/to-layers", headers=demo_headers, json={})
    assert published.status_code == 200, published.text
    db_session.expire_all()
    auto_after = db_session.scalar(
        select(func.count())
        .select_from(LayerObject)
        .join(Layer, LayerObject.layer_id == Layer.id)
        .where(Layer.user_id == agronom.id, LayerObject.origin == "auto")
    ) or 0
    assert auto_after > auto_before

    listed = client.get("/api/v1/layers/", headers=demo_headers)
    crop_layer = next(item for item in listed.json() if item.get("class_id") == 2)
    objects = client.get(f"/api/v1/layers/{crop_layer['id']}/objects", headers=demo_headers)
    assert objects.status_code == 200
    assert objects.json()

    opened = client.get(f"/api/v1/activity/{task_id}/open", headers=demo_headers)
    assert opened.status_code == 200
    downloaded = client.get(f"/api/v1/activity/{task_id}/result", headers=demo_headers)
    assert downloaded.status_code == 200

    blocked = client.delete(f"/api/v1/tasks/{task_id}", headers=demo_headers)
    assert blocked.status_code == 409


def test_geo_bounds_georeferences_pixels(client, demo_headers, db_session, monkeypatch):
    from app.ml_service.schemas import InferenceFeature, InferenceResponse

    def pixel_infer(*_args, **_kwargs) -> InferenceResponse:
        ring = [[[0, 0], [8, 0], [8, 8], [0, 8], [0, 0]]]
        return InferenceResponse(
            model="segformer",
            polygons=[
                InferenceFeature(
                    class_id=2,
                    confidence=0.9,
                    geometry={"type": "Polygon", "coordinates": ring},
                )
            ],
            points=[],
        )

    _patch_eager_infer(monkeypatch, infer=pixel_infer)
    bounds = {"west": 27.0, "south": 53.0, "east": 27.8, "north": 53.8}
    created = client.post(
        "/api/v1/tasks/",
        headers=demo_headers,
        files={"file": ("aoi.png", tiny_png(), "image/png")},
        data={
            "model": "segformer",
            "confidence": "0.5",
            "geo_bounds": json.dumps(bounds),
        },
    )
    assert created.status_code == 200, created.text
    task_id = uuid.UUID(str(created.json()["task_id"]))
    db_session.expire_all()
    image = db_session.scalar(select(Image).where(Image.task_id == task_id))
    assert image is not None
    poly = db_session.scalar(select(PolygonObject).where(PolygonObject.image_id == image.id))
    assert poly is not None
    from geoalchemy2.shape import to_shape

    geom = to_shape(poly.geom)
    xs, ys = geom.exterior.xy
    assert min(xs) == pytest.approx(27.0, abs=0.05)
    assert max(xs) == pytest.approx(27.8, abs=0.05)
    assert min(ys) == pytest.approx(53.0, abs=0.05)
    assert max(ys) == pytest.approx(53.8, abs=0.05)


def test_delete_pending_or_failed_task(client, demo_headers, db_session, monkeypatch):
    monkeypatch.setattr("app.tasks_service.service.upload_bytes", lambda *a, **k: k.get("key") or a[0])

    created = client.post(
        "/api/v1/tasks/",
        headers=demo_headers,
        files={"file": ("queued.png", tiny_png(), "image/png")},
        data={"model": "segformer", "confidence": "0.5"},
    )
    assert created.status_code == 200, created.text
    task_id = uuid.UUID(str(created.json()["task_id"]))
    db_session.expire_all()
    task = db_session.get(ProcessingTask, task_id)
    assert task is not None
    if task.status == "COMPLETED":
        task.status = "FAILED"
        db_session.commit()

    deleted = client.delete(f"/api/v1/tasks/{task_id}", headers=demo_headers)
    assert deleted.status_code == 200, deleted.text
    db_session.expire_all()
    assert db_session.get(ProcessingTask, task_id) is None


def test_dzz_routes_and_disconnect(client, demo_headers, db_session):
    status = client.get("/api/v1/dzz/status", headers=demo_headers)
    assert status.status_code == 200
    check = client.post("/api/v1/dzz/check", headers=demo_headers)
    assert check.status_code == 200
    tiles = client.get("/api/v1/dzz/tiles/1/1/1", headers=demo_headers)
    assert tiles.status_code == 200
    regions = client.get("/api/v1/dzz/regions", headers=demo_headers)
    assert regions.status_code in {200, 404}
    caps = client.get("/api/v1/dzz/wmts/capabilities", headers=demo_headers)
    assert caps.status_code in {200, 404}
    connect = client.post(
        "/api/v1/dzz/connect",
        headers=demo_headers,
        json={"login": "bad", "password": "bad", "service_url": "https://127.0.0.1:1"},
    )
    assert connect.status_code in {401, 503}
    disconnect = client.post("/api/v1/dzz/disconnect", headers=demo_headers)
    assert disconnect.status_code == 200
    db_session.expire_all()
    agronom = _user(db_session, "agronom@agrovision.dev")
    assert db_session.scalar(select(DzzConnection).where(DzzConnection.user_id == agronom.id)) is None


def test_delete_fresh_account_removes_user_row(client, db_session):
    email = f"gone-{uuid.uuid4().hex[:8]}@example.com"
    register = client.post(
        "/api/v1/auth/register",
        json={
            "first_name": "Удалить",
            "last_name": "Аккаунт",
            "email": email,
            "organization": "КФХ",
            "role": "Оператор",
            "password": DEMO_PASSWORD,
            "password_repeat": DEMO_PASSWORD,
        },
    )
    assert register.status_code == 200, register.text
    headers = {"Authorization": f"Bearer {register.json()['access_token']}"}
    deleted = client.request(
        "DELETE",
        "/api/v1/users/me",
        headers={**headers, "Content-Type": "application/json"},
        content=json.dumps({"password": DEMO_PASSWORD}),
    )
    assert deleted.status_code == 204
    db_session.expire_all()
    assert db_session.scalar(select(User).where(User.username == email)) is None
