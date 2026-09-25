import json
import uuid

from tests.conftest import empty_inference, tiny_png


def test_auth_login_refresh_me(client):
    email = f"auth-{uuid.uuid4().hex[:8]}@example.com"
    register = client.post(
        "/api/v1/auth/register",
        json={
            "first_name": "Иван",
            "last_name": "Петров",
            "email": email,
            "organization": "КФХ",
            "role": "Оператор",
            "password": "ValidPass1!",
            "password_repeat": "ValidPass1!",
        },
    )
    assert register.status_code == 200, register.text
    tokens = register.json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "ValidPass1!", "remember_me": True},
    )
    assert login.status_code == 200

    refresh = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refresh.status_code == 200

    me = client.get("/api/v1/users/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["email"] == email

    patched = client.patch("/api/v1/users/me", headers=headers, json={"organization": "ООО Поле"})
    assert patched.status_code == 200
    assert patched.json()["organization"] == "ООО Поле"

    logout = client.post("/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert logout.status_code == 200

    reset = client.post("/api/v1/auth/password-reset/request", json={"email": email})
    assert reset.status_code == 200, reset.text
    body = reset.json()
    assert "detail" in body
    if body.get("dev_code"):
        confirm_ok = client.post(
            "/api/v1/auth/password-reset/confirm",
            json={
                "email": email,
                "code": body["dev_code"],
                "new_password": "ValidPass2!",
                "new_password_repeat": "ValidPass2!",
            },
        )
        assert confirm_ok.status_code == 200, confirm_ok.text
        return
    confirm = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={
            "email": email,
            "code": "0000",
            "new_password": "ValidPass2!",
            "new_password_repeat": "ValidPass2!",
        },
    )
    assert confirm.status_code in {400, 404, 422}


def test_activity_list(client, auth_headers):
    response = client.get("/api/v1/activity/", headers=auth_headers)
    assert response.status_code == 200
    assert "items" in response.json()


def test_layers_folders_objects_merge(client, auth_headers):
    created = client.post(
        "/api/v1/layers/",
        headers=auth_headers,
        json={"name": "Пользовательский", "color": "#FF0000"},
    )
    assert created.status_code == 200, created.text
    layer_id = created.json()["id"]

    listed = client.get("/api/v1/layers/", headers=auth_headers)
    assert listed.status_code == 200
    assert any(item["id"] == layer_id for item in listed.json())

    folder = client.post("/api/v1/folders/", headers=auth_headers, json={"name": "Сезон"})
    assert folder.status_code == 200
    folder_id = folder.json()["id"]
    move = client.post(
        f"/api/v1/folders/{folder_id}/items",
        headers=auth_headers,
        json={"layer_id": layer_id},
    )
    assert move.status_code == 200

    geom = {"type": "Polygon", "coordinates": [[[27.0, 53.0], [27.1, 53.0], [27.1, 53.1], [27.0, 53.0]]]}
    obj1 = client.post(
        f"/api/v1/layers/{layer_id}/objects",
        headers=auth_headers,
        json={"name": "А", "geom": geom, "origin": "manual"},
    )
    obj2 = client.post(
        f"/api/v1/layers/{layer_id}/objects",
        headers=auth_headers,
        json={"name": "Б", "geom": geom, "origin": "manual"},
    )
    assert obj1.status_code == 200, obj1.text
    assert obj2.status_code == 200, obj2.text
    got = client.get(f"/api/v1/objects/{obj1.json()['id']}", headers=auth_headers)
    assert got.status_code == 200
    listed_objects = client.get(f"/api/v1/layers/{layer_id}/objects", headers=auth_headers)
    assert listed_objects.status_code == 200, listed_objects.text
    ids = {item["id"] for item in listed_objects.json()}
    assert obj1.json()["id"] in ids
    assert obj2.json()["id"] in ids

    merged = client.post(
        "/api/v1/objects/merge",
        headers=auth_headers,
        json={"object_ids": [obj1.json()["id"], obj2.json()["id"]]},
    )
    assert merged.status_code == 200, merged.text

    other = client.post(
        "/api/v1/layers/",
        headers=auth_headers,
        json={"name": "Другой", "color": "#00FF00"},
    )
    obj3 = client.post(
        f"/api/v1/layers/{other.json()['id']}/objects",
        headers=auth_headers,
        json={"name": "В", "geom": geom, "origin": "manual"},
    )
    conflict = client.post(
        "/api/v1/objects/merge",
        headers=auth_headers,
        json={"object_ids": [merged.json()["id"], obj3.json()["id"]]},
    )
    assert conflict.status_code == 409

    auto_layers = [item for item in listed.json() if item["kind"] == "auto"]
    assert len(auto_layers) >= 6
    denied = client.delete(f"/api/v1/layers/{auto_layers[0]['id']}", headers=auth_headers)
    assert denied.status_code == 403


def test_register_creates_auto_layers_only(client, auth_headers):
    layers = client.get("/api/v1/layers/", headers=auth_headers)
    assert layers.status_code == 200
    items = layers.json()
    auto = [item for item in items if item["kind"] == "auto"]
    user = [item for item in items if item["kind"] != "auto"]
    assert len(auto) >= 6
    assert user == []


def test_register_rejects_free_text_role(client):
    email = f"role-{uuid.uuid4().hex[:8]}@example.com"
    response = client.post(
        "/api/v1/auth/register",
        json={
            "first_name": "Иван",
            "last_name": "Петров",
            "email": email,
            "organization": "КФХ",
            "role": "ГИС-специалист",
            "password": "ValidPass1!",
            "password_repeat": "ValidPass1!",
        },
    )
    assert response.status_code == 422


def test_delete_me_requires_password(client, auth_headers):
    response = client.delete("/api/v1/users/me", headers=auth_headers)
    assert response.status_code == 422


def test_delete_me_wrong_password_is_forbidden(client, auth_headers):
    response = client.request(
        "DELETE",
        "/api/v1/users/me",
        headers={**auth_headers, "Content-Type": "application/json"},
        content=json.dumps({"password": "WrongPass1!"}),
    )
    assert response.status_code == 403
    assert "парол" in response.json()["detail"].lower()


def test_patch_me_password_requires_current(client, auth_headers):
    missing = client.patch(
        "/api/v1/users/me",
        headers=auth_headers,
        json={"password": "ValidPass2!", "password_repeat": "ValidPass2!"},
    )
    assert missing.status_code == 422
    wrong = client.patch(
        "/api/v1/users/me",
        headers=auth_headers,
        json={
            "current_password": "WrongPass1!",
            "password": "ValidPass2!",
            "password_repeat": "ValidPass2!",
        },
    )
    assert wrong.status_code == 403


def test_import_export(client, auth_headers):
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [27.5, 53.9]},
                "properties": {"name": "Точка"},
            }
        ],
    }
    files = {"file": ("import.geojson", json.dumps(geojson).encode("utf-8"), "application/geo+json")}
    imported = client.post("/api/v1/layers/import", headers=auth_headers, files=files)
    assert imported.status_code == 200, imported.text
    exported = client.post("/api/v1/layers/export", headers=auth_headers, json={"format": "geojson"})
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("application/")


def test_models_and_classes(client, auth_headers):
    models = client.get("/api/v1/models/", headers=auth_headers)
    assert models.status_code == 200
    health = client.get("/api/v1/models/health", headers=auth_headers)
    assert health.status_code == 200
    assert "models" in health.json()
    classes = client.get("/api/v1/classes/", headers=auth_headers)
    assert classes.status_code == 200
    assert len(classes.json()) >= 6


def test_dzz_routes_do_not_crash(client, auth_headers):
    status = client.get("/api/v1/dzz/status", headers=auth_headers)
    assert status.status_code == 200
    check = client.post("/api/v1/dzz/check", headers=auth_headers)
    assert check.status_code == 200
    tiles = client.get("/api/v1/dzz/tiles/1/1/1", headers=auth_headers)
    assert tiles.status_code == 200
    regions = client.get("/api/v1/dzz/regions", headers=auth_headers)
    assert regions.status_code in {200, 404}
    connect = client.post(
        "/api/v1/dzz/connect",
        headers=auth_headers,
        json={"login": "bad", "password": "bad", "service_url": "https://127.0.0.1:1"},
    )
    assert connect.status_code in {401, 503}


def test_tasks_calls_runtime(client, auth_headers, monkeypatch):
    called = {"infer": 0, "upload": 0}

    def fake_infer(file_bytes, filename, request):
        called["infer"] += 1
        return empty_inference()

    def fake_upload(key, data, content_type="application/octet-stream"):
        called["upload"] += 1
        return key

    def fake_send(name, args=None, kwargs=None, **_extra):
        from app.tasks_service.workers import run_inference

        run_inference(*(args or []), **(kwargs or {}))

    monkeypatch.setattr("app.ml_service.runtime.infer_sync", fake_infer)
    monkeypatch.setattr("app.tasks_service.workers.infer_sync", fake_infer)
    monkeypatch.setattr("app.tasks_service.service.upload_bytes", fake_upload)
    monkeypatch.setattr("app.tasks_service.workers.download_bytes", lambda key: tiny_png())
    monkeypatch.setattr("app.core.celery_app.celery_app.send_task", fake_send)

    files = {"file": ("field.png", tiny_png(), "image/png")}
    created = client.post(
        "/api/v1/tasks/",
        headers=auth_headers,
        files=files,
        data={"model": "segformer", "confidence": "0.5"},
    )
    assert created.status_code == 200, created.text
    task_id = created.json()["task_id"]
    listed = client.get("/api/v1/tasks/", headers=auth_headers)
    assert listed.status_code == 200
    got = client.get(f"/api/v1/tasks/{task_id}", headers=auth_headers)
    assert got.status_code == 200
    assert called["upload"] >= 1
    assert called["infer"] >= 1
