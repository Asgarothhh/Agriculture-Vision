from app.users_service.schemas import PasswordResetConfirm, ProfileUpdate, RegisterRequest
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


def test_register_schema_rejects_unknown_role():
    with pytest.raises(ValidationError):
        RegisterRequest(
            first_name="Иван",
            last_name="Петров",
            email="ivan@example.com",
            organization="КФХ",
            role="ГИС-специалист",
            password="ValidPass1!",
            password_repeat="ValidPass1!",
        )
    payload = ProfileUpdate(first_name="Анна")
    assert payload.first_name == "Анна"
    assert payload.password is None


def test_profile_update_password_requires_current():
    with pytest.raises(ValidationError):
        ProfileUpdate(password="ValidPass2!", password_repeat="ValidPass2!")
    payload = ProfileUpdate(
        current_password="ValidPass1!",
        password="ValidPass2!",
        password_repeat="ValidPass2!",
    )
    assert payload.current_password == "ValidPass1!"
    assert payload.password == "ValidPass2!"


def test_password_reset_confirm_requires_four_digits():
    with pytest.raises(ValidationError):
        PasswordResetConfirm(
            email="ivan@example.com",
            code="123456",
            new_password="ValidPass2!",
            new_password_repeat="ValidPass2!",
        )
    payload = PasswordResetConfirm(
        email="ivan@example.com",
        code="1234",
        new_password="ValidPass2!",
        new_password_repeat="ValidPass2!",
    )
    assert payload.code == "1234"


def test_openapi_has_auth_and_profile_paths(client):
    spec = client.get("/api/v1/openapi.json").json()
    paths = spec["paths"]
    assert "/api/v1/auth/register" in paths
    assert "/api/v1/auth/login" in paths
    assert "/api/v1/auth/refresh" in paths
    assert "/api/v1/users/me" in paths
    assert "/api/v1/activity/" in paths
