from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.core.security import is_strong_password


class RegisterRequest(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    organization: str = Field(default="", max_length=255)
    role: str = Field(default="Агроном", max_length=100)
    password: str
    password_repeat: str

    @field_validator("password")
    @classmethod
    def _password_strength(cls, value: str) -> str:
        if not is_strong_password(value):
            raise ValueError(
                "Пароль: минимум 8 символов, строчная и заглавная буквы, спецсимвол"
            )
        return value

    @model_validator(mode="after")
    def _passwords_match(self) -> RegisterRequest:
        if self.password != self.password_repeat:
            raise ValueError("Пароли не совпадают")
        return self


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    remember_me: bool = False


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6)
    new_password: str
    new_password_repeat: str

    @field_validator("new_password")
    @classmethod
    def _password_strength(cls, value: str) -> str:
        if not is_strong_password(value):
            raise ValueError(
                "Пароль: минимум 8 символов, строчная и заглавная буквы, спецсимвол"
            )
        return value

    @model_validator(mode="after")
    def _passwords_match(self) -> PasswordResetConfirm:
        if self.new_password != self.new_password_repeat:
            raise ValueError("Пароли не совпадают")
        return self


class ProfileUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    organization: str | None = Field(default=None, max_length=255)
    avatar_meta: dict[str, Any] | None = None
    password: str | None = None
    password_repeat: str | None = None

    @model_validator(mode="after")
    def _password_rules(self) -> ProfileUpdate:
        if self.password is None:
            return self
        if not is_strong_password(self.password):
            raise ValueError(
                "Пароль: минимум 8 символов, строчная и заглавная буквы, спецсимвол"
            )
        if self.password != self.password_repeat:
            raise ValueError("Пароли не совпадают")
        return self


class ProfileResponse(BaseModel):
    id: UUID
    email: str
    first_name: str
    last_name: str
    organization: str
    role: str
    avatar: dict[str, Any] | None = None
    exports_count: int = 0
    processed_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}
