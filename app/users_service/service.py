from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import ADMIN_ROLE, AGRONOMIST_ROLE, OPERATOR_ROLE
from app.core.email import MailUnavailableError, send_email
from app.core.seed import SYSTEM_LAYERS
from app.core.security import (
    create_access_token,
    create_refresh_token,
    generate_reset_code,
    hash_password,
    new_jti,
    verify_password,
)
from app.layers_service.models import Layer
from app.tasks_service.models import ProcessingTask
from app.users_service.models import ActivityLog, PasswordResetCode, RefreshToken, Role, User
from app.users_service.schemas import (
    LoginRequest,
    PasswordResetConfirm,
    ProfileUpdate,
    RegisterRequest,
    TokenResponse,
)

ROLE_ALIASES = {
    "администратор": ADMIN_ROLE,
    "administrator": ADMIN_ROLE,
    "admin": ADMIN_ROLE,
    "агроном": AGRONOMIST_ROLE,
    "agronomist": AGRONOMIST_ROLE,
    "оператор": OPERATOR_ROLE,
    "operator": OPERATOR_ROLE,
}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _resolve_role_name(raw: str) -> str:
    key = (raw or "").strip().lower()
    return ROLE_ALIASES.get(key, AGRONOMIST_ROLE)


async def _role_by_name(db: AsyncSession, name: str) -> Role:
    role = (await db.execute(select(Role).where(Role.name == name))).scalar_one_or_none()
    if role is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Roles are not seeded")
    return role


async def _issue_tokens(db: AsyncSession, user: User, remember_me: bool) -> TokenResponse:
    jti = new_jti()
    refresh = create_refresh_token(user.id, jti, remember_me)
    payload = decode_exp(refresh)
    db.add(
        RefreshToken(
            jti=jti,
            user_id=user.id,
            expires_at=payload,
            remember_me=remember_me,
        )
    )
    await db.commit()
    return TokenResponse(
        access_token=create_access_token(user.id, extra={"role": user.role.name if user.role else ""}),
        refresh_token=refresh,
    )


def decode_exp(token: str) -> datetime:
    from app.core.security import decode_token

    payload = decode_token(token)
    exp = payload["exp"]
    if isinstance(exp, datetime):
        return exp
    return datetime.fromtimestamp(int(exp), tz=UTC)


async def register_user(db: AsyncSession, data: RegisterRequest) -> TokenResponse:
    existing = (
        await db.execute(select(User).where(User.username == str(data.email).lower()))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Email already registered")

    role = await _role_by_name(db, _resolve_role_name(data.role))
    user = User(
        username=str(data.email).lower(),
        first_name=data.first_name,
        last_name=data.last_name,
        organization=data.organization,
        user_role=data.role,
        password_hash=hash_password(data.password),
        role_id=role.id,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user, attribute_names=["role"])
    for item in SYSTEM_LAYERS:
        db.add(
            Layer(
                user_id=user.id,
                name=item["name"],
                color=item["color"],
                kind="auto",
                class_id=item["class_id"],
                is_visible=True,
            )
        )
    db.add(
        ActivityLog(
            user_id=user.id,
            category="account",
            action="Регистрация",
            payload={"email": user.username},
        )
    )
    return await _issue_tokens(db, user, remember_me=False)


async def login_user(db: AsyncSession, data: LoginRequest) -> TokenResponse:
    user = (
        await db.execute(
            select(User).options(selectinload(User.role)).where(User.username == str(data.email).lower())
        )
    ).scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(data.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Неверный email или пароль")
    db.add(
        ActivityLog(
            user_id=user.id,
            category="account",
            action="Вход в систему",
            payload={"email": user.username},
        )
    )
    return await _issue_tokens(db, user, data.remember_me)


async def refresh_tokens(db: AsyncSession, refresh_token: str) -> TokenResponse:
    from app.core.security import decode_token

    try:
        payload = decode_token(refresh_token)
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    if payload.get("type") != "refresh":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
    jti = payload.get("jti")
    stored = (await db.execute(select(RefreshToken).where(RefreshToken.jti == jti))).scalar_one_or_none()
    if stored is None or stored.revoked_at is not None or stored.expires_at < _utcnow():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Refresh token revoked or expired")
    stored.revoked_at = _utcnow()
    user = (
        await db.execute(select(User).options(selectinload(User.role)).where(User.id == stored.user_id))
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="User inactive")
    return await _issue_tokens(db, user, stored.remember_me)


async def logout_user(db: AsyncSession, refresh_token: str) -> None:
    from app.core.security import decode_token

    try:
        payload = decode_token(refresh_token)
    except ValueError:
        return
    jti = payload.get("jti")
    stored = (await db.execute(select(RefreshToken).where(RefreshToken.jti == jti))).scalar_one_or_none()
    if stored and stored.revoked_at is None:
        stored.revoked_at = _utcnow()
        await db.commit()


async def request_password_reset(db: AsyncSession, email: str) -> None:
    user = (
        await db.execute(select(User).where(User.username == email.lower()))
    ).scalar_one_or_none()
    if user is None:
        return
    last = (
        await db.execute(
            select(PasswordResetCode)
            .where(PasswordResetCode.user_id == user.id)
            .order_by(PasswordResetCode.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if last and last.created_at and (_utcnow() - last.created_at.replace(tzinfo=UTC)) < timedelta(minutes=1):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail="Повторная отправка не чаще 1 раза в минуту")
    code = generate_reset_code()
    db.add(
        PasswordResetCode(
            code=code,
            user_id=user.id,
            expires_at=_utcnow() + timedelta(minutes=15),
        )
    )
    await db.commit()
    try:
        await send_email(
            user.username,
            "Код восстановления пароля АгроВижион",
            f"Ваш код: {code}. Действителен 15 минут.",
        )
    except MailUnavailableError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Почтовый сервер недоступен. Попробуйте позже.",
        ) from exc


async def confirm_password_reset(db: AsyncSession, data: PasswordResetConfirm) -> None:
    user = (
        await db.execute(select(User).where(User.username == str(data.email).lower()))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Неверный код")
    row = (
        await db.execute(
            select(PasswordResetCode)
            .where(
                PasswordResetCode.user_id == user.id,
                PasswordResetCode.code == data.code,
                PasswordResetCode.used_at.is_(None),
            )
            .order_by(PasswordResetCode.created_at.desc())
        )
    ).scalars().first()
    if row is None or row.expires_at < _utcnow():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Неверный или просроченный код")
    row.used_at = _utcnow()
    user.password_hash = hash_password(data.new_password)
    await db.commit()


async def profile_payload(db: AsyncSession, user: User) -> dict:
    exports_count = (
        await db.execute(
            select(func.count())
            .select_from(ActivityLog)
            .where(ActivityLog.user_id == user.id, ActivityLog.category == "export")
        )
    ).scalar_one()
    processed_count = (
        await db.execute(
            select(func.count())
            .select_from(ProcessingTask)
            .where(ProcessingTask.user_id == user.id, ProcessingTask.status == "COMPLETED")
        )
    ).scalar_one()
    return {
        "id": user.id,
        "email": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "organization": user.organization,
        "role": user.role.name if user.role else user.user_role,
        "avatar": user.avatar_meta,
        "exports_count": int(exports_count or 0),
        "processed_count": int(processed_count or 0),
        "created_at": user.created_at,
    }


async def update_profile(db: AsyncSession, user: User, data: ProfileUpdate) -> User:
    if data.first_name is not None:
        user.first_name = data.first_name
    if data.last_name is not None:
        user.last_name = data.last_name
    if data.organization is not None:
        user.organization = data.organization
    if data.avatar_meta is not None:
        user.avatar_meta = data.avatar_meta
    if data.password:
        user.password_hash = hash_password(data.password)
    await db.commit()
    await db.refresh(user)
    return user


async def delete_account(db: AsyncSession, user: User) -> None:
    await db.delete(user)
    await db.commit()
