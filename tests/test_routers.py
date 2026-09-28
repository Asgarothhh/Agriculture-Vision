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
            "code": "000000",
            "new_password": "ValidPass2!",
            "new_password_repeat": "ValidPass2!",
        },
    )
    assert confirm.status_code in {400, 404, 422}


def test_activity_list(client, auth_headers):
    response = client.get("/api/v1/activity/", headers=auth_headers)
    assert response.status_code == 200
    assert "items" in response.json()


def test_ui_events_are_added_to_history(client, auth_headers):
    created = client.post(
        "/api/v1/activity/",
        headers=auth_headers,
        json={"category": "map_tools", "action": "Выбран инструмент: Линейка", "payload": {"tool": "ruler"}},
    )
    assert created.status_code == 201, created.text
    items = client.get("/api/v1/activity/", headers=auth_headers, params={"q": "Выбран инструмент"}).json()["items"]
    assert items[0]["category"] == "map_tools"
    assert items[0]["payload"] == {"tool": "ruler", "source": "ui"}

    bad_category = client.post("/api/v1/activity/", headers=auth_headers, json={"category": "admin", "action": "x"})
    assert bad_category.status_code == 422
    blank = client.post("/api/v1/activity/", headers=auth_headers, json={"category": "account", "action": "   "})
    assert blank.status_code == 422
    too_big = client.post(
        "/api/v1/activity/",
        headers=auth_headers,
        json={"category": "account", "action": "x", "payload": {"blob": "a" * 5000}},
    )
    assert too_big.status_code == 422
    anonymous = client.post("/api/v1/activity/", json={"category": "account", "action": "x"})
    assert anonymous.status_code in {401, 403}


def test_activity_filters_by_several_categories(client, auth_headers):
    layer = client.post("/api/v1/layers/", headers=auth_headers, json={"name": "Фильтр", "color": "#123456"}).json()
    ring = [[27.45, 53.88], [27.46, 53.88], [27.46, 53.89], [27.45, 53.88]]
    client.post(
        f"/api/v1/layers/{layer['id']}/objects",
        headers=auth_headers,
        json={"name": "Поле", "geom": {"type": "Polygon", "coordinates": [ring]}, "origin": "manual"},
    )
    both = client.get(
        "/api/v1/activity/", headers=auth_headers, params=[("category", "account"), ("category", "map_tools")]
    ).json()
    assert {item["category"] for item in both["items"]} == {"account", "map_tools"}
    only_export = client.get("/api/v1/activity/", headers=auth_headers, params={"category": "export"}).json()
    assert only_export["items"] == []
    assert only_export["total"] == 0
    assert only_export["total_all"] >= both["total"] > 0


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


def test_patch_me_password_change_revokes_sessions(client):
    email = f"pw-{uuid.uuid4().hex[:10]}@example.com"
    registered = client.post(
        "/api/v1/auth/register",
        json={
            "first_name": "Тест", "last_name": "Пароль", "email": email, "organization": "КФХ",
            "role": "Агроном", "password": "ValidPass1!", "password_repeat": "ValidPass1!",
        },
    )
    assert registered.status_code == 200, registered.text
    tokens = registered.json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    same = client.patch(
        "/api/v1/users/me",
        headers=headers,
        json={"current_password": "ValidPass1!", "password": "ValidPass1!", "password_repeat": "ValidPass1!"},
    )
    assert same.status_code == 400

    changed = client.patch(
        "/api/v1/users/me",
        headers=headers,
        json={"current_password": "ValidPass1!", "password": "ValidPass2!", "password_repeat": "ValidPass2!"},
    )
    assert changed.status_code == 200, changed.text
    stale = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert stale.status_code == 401
    old_login = client.post("/api/v1/auth/login", json={"email": email, "password": "ValidPass1!"})
    assert old_login.status_code == 401
    new_login = client.post("/api/v1/auth/login", json={"email": email, "password": "ValidPass2!"})
    assert new_login.status_code == 200
    history = client.get("/api/v1/activity/", headers=headers, params={"q": "Пароль изменён"}).json()
    assert history["items"]


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
    assert int(exported.headers["x-exported-count"]) >= 1
    me = client.get("/api/v1/users/me", headers=auth_headers).json()
    assert me["exports_count"] == 1  # the import itself is not an export
    history = client.get("/api/v1/activity/", headers=auth_headers, params={"category": "map_tools"}).json()
    assert any("import.geojson" in item["action"] for item in history["items"])


def test_layer_can_leave_folder_and_foreign_folder_is_rejected(client, auth_headers):
    layer = client.post("/api/v1/layers/", headers=auth_headers, json={"name": "В папке", "color": "#123456"}).json()
    folder = client.post("/api/v1/folders/", headers=auth_headers, json={"name": "Папка"}).json()
    moved = client.patch(f"/api/v1/layers/{layer['id']}", headers=auth_headers, json={"folder_id": folder["id"]})
    assert moved.json()["folder_id"] == folder["id"]
    renamed = client.patch(f"/api/v1/layers/{layer['id']}", headers=auth_headers, json={"name": "Всё ещё в папке"})
    assert renamed.json()["folder_id"] == folder["id"]
    detached = client.patch(f"/api/v1/layers/{layer['id']}", headers=auth_headers, json={"folder_id": None})
    assert detached.json()["folder_id"] is None
    foreign = client.patch(
        f"/api/v1/layers/{layer['id']}", headers=auth_headers, json={"folder_id": str(uuid.uuid4())}
    )
    assert foreign.status_code == 404


def test_import_rejects_empty_and_broken_files(client, auth_headers):
    before = client.get("/api/v1/layers/", headers=auth_headers).json()
    empty = {"type": "FeatureCollection", "features": []}
    cases = [
        ("empty.geojson", json.dumps(empty).encode("utf-8"), "нет объектов"),
        ("broken.geojson", b"{not json", "Не удалось прочитать"),
        ("list.geojson", b"[1, 2]", "Не удалось прочитать"),
    ]
    for name, content, message in cases:
        response = client.post(
            "/api/v1/layers/import", headers=auth_headers, files={"file": (name, content, "application/geo+json")}
        )
        assert response.status_code == 400, (name, response.text)
        assert message in response.json()["detail"]
    after = client.get("/api/v1/layers/", headers=auth_headers).json()
    assert len(after) == len(before)  # no ghost layer


def test_export_without_objects_is_conflict(client, auth_headers):
    layers = client.get("/api/v1/layers/", headers=auth_headers).json()
    for layer in layers:
        client.patch(f"/api/v1/layers/{layer['id']}", headers=auth_headers, json={"is_visible": False})
    response = client.post("/api/v1/layers/export", headers=auth_headers, json={"format": "shapefile"})
    assert response.status_code == 409
    assert response.json()["detail"] == "Нет объектов для экспорта"


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
    assert connect.status_code in {400, 401, 503}


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


def test_object_folder_and_crop_are_returned_and_exported(client, auth_headers):
    layer = client.post("/api/v1/layers/", headers=auth_headers, json={"name": "Культуры", "color": "#00AA00"}).json()
    geom = {"type": "Polygon", "coordinates": [[[27.0, 53.0], [27.01, 53.0], [27.01, 53.01], [27.0, 53.0]]]}
    obj = client.post(
        f"/api/v1/layers/{layer['id']}/objects", headers=auth_headers, json={"name": "Поле", "geom": geom}
    ).json()
    assert obj["folder_id"] is None
    assert obj["crop"] is None

    # В1: a single object put into a folder stays there after reload
    folder = client.post("/api/v1/folders/", headers=auth_headers, json={"name": "Участок 1"}).json()
    moved = client.post(f"/api/v1/folders/{folder['id']}/items", headers=auth_headers, json={"object_id": obj["id"]})
    assert moved.status_code == 200
    listed = client.get(f"/api/v1/layers/{layer['id']}/objects", headers=auth_headers).json()
    assert listed[0]["folder_id"] == folder["id"]

    # В2: crop set, kept when omitted, cleared by null
    with_crop = client.patch(f"/api/v1/objects/{obj['id']}", headers=auth_headers, json={"crop": "Пшеница"})
    assert with_crop.status_code == 200, with_crop.text
    assert with_crop.json()["crop"] == "Пшеница"
    renamed = client.patch(f"/api/v1/objects/{obj['id']}", headers=auth_headers, json={"name": "Поле 2"})
    assert renamed.json()["crop"] == "Пшеница"
    assert renamed.json()["folder_id"] == folder["id"]

    exported = client.post(
        "/api/v1/layers/export", headers=auth_headers, json={"format": "geojson", "layer_ids": [layer["id"]]}
    )
    assert exported.status_code == 200, exported.text
    props = [f["properties"] for f in exported.json()["features"]]
    assert props[0]["crop"] == "Пшеница"

    cleared = client.patch(f"/api/v1/objects/{obj['id']}", headers=auth_headers, json={"crop": None})
    assert cleared.json()["crop"] is None
    too_long = client.patch(f"/api/v1/objects/{obj['id']}", headers=auth_headers, json={"crop": "x" * 121})
    assert too_long.status_code == 422

    detached = client.post(
        f"/api/v1/folders/{folder['id']}/items", headers=auth_headers, json={"object_id": obj["id"], "detach": True}
    )
    assert detached.status_code == 200
    assert client.get(f"/api/v1/objects/{obj['id']}", headers=auth_headers).json()["folder_id"] is None
