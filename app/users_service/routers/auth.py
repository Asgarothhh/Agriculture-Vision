from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.ratelimit import limiter
from app.users_service import service
from app.users_service.schemas import (
    LoginRequest,
    LogoutRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse)
@limiter.limit("10/minute")
async def register(request: Request, payload: RegisterRequest, db: Annotated[AsyncSession, Depends(get_db)]):
    return await service.register_user(db, payload)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(request: Request, payload: LoginRequest, db: Annotated[AsyncSession, Depends(get_db)]):
    return await service.login_user(db, payload)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest, db: Annotated[AsyncSession, Depends(get_db)]):
    return await service.refresh_tokens(db, payload.refresh_token)


@router.post("/logout")
async def logout(payload: LogoutRequest, db: Annotated[AsyncSession, Depends(get_db)]):
    await service.logout_user(db, payload.refresh_token)
    return {"detail": "ok"}


@router.post("/password-reset/request")
@limiter.limit("5/minute")
async def password_reset_request(
    request: Request,
    payload: PasswordResetRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await service.request_password_reset(db, str(payload.email))


@router.post("/password-reset/confirm")
async def password_reset_confirm(
    payload: PasswordResetConfirm,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await service.confirm_password_reset(db, payload)
    return {"detail": "Пароль обновлён"}
