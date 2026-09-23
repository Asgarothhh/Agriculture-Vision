from app.users_service.schemas import ProfileUpdate, RegisterRequest
from pydantic import ValidationError
import pytest


def test_register_schema_rejects_weak_password():
    with pytest.raises(ValidationError):
        RegisterRequest(
            first_name="Иван",
            last_name="Петров",
            email="ivan@example.com",
            organization="КФХ",
            role="Агроном",
            password="weak",
            password_repeat="weak",
        )


def test_register_schema_rejects_mismatch():
    with pytest.raises(ValidationError):
        RegisterRequest(
            first_name="Иван",
            last_name="Петров",
            email="ivan@example.com",
            organization="КФХ",
            role="Агроном",
            password="ValidPass1!",
            password_repeat="ValidPass2!",
        )


def test_profile_update_optional_password():
    payload = ProfileUpdate(first_name="Анна")
    assert payload.first_name == "Анна"
    assert payload.password is None


def test_openapi_has_auth_and_profile_paths(client):
    spec = client.get("/api/v1/openapi.json").json()
    paths = spec["paths"]
    assert "/api/v1/auth/register" in paths
    assert "/api/v1/auth/login" in paths
    assert "/api/v1/auth/refresh" in paths
    assert "/api/v1/users/me" in paths
    assert "/api/v1/activity/" in paths
