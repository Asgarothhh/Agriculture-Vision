from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import bcrypt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from jose import JWTError, jwt

from app.core.config import get_settings

ALGORITHM = "HS256"


def _now() -> datetime:
    return datetime.now(UTC)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def is_strong_password(password: str) -> bool:
    value = password or ""
    if len(value) < 8:
        return False
    if not any(ch.islower() or ch in "абвгдеёжзийклмнопрстуфхцчшщъыьэюя" for ch in value):
        return False
    if not any(ch.isupper() or ch in "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ" for ch in value):
        return False
    if not any(not ch.isalnum() for ch in value):
        return False
    return True


def create_access_token(subject: str | UUID, extra: dict[str, Any] | None = None) -> str:
    settings = get_settings()
    expire = _now() + timedelta(minutes=settings.access_token_ttl_min)
    payload = {"sub": str(subject), "exp": expire, "type": "access"}
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def create_refresh_token(
    subject: str | UUID,
    jti: str,
    remember_me: bool,
) -> str:
    settings = get_settings()
    ttl_days = settings.refresh_token_ttl_days if remember_me else 1
    expire = _now() + timedelta(days=ttl_days)
    payload = {
        "sub": str(subject),
        "exp": expire,
        "type": "refresh",
        "jti": jti,
        "remember_me": remember_me,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise ValueError("Invalid token") from exc


def generate_reset_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def new_jti() -> str:
    return secrets.token_urlsafe(32)


def _aes_key() -> bytes:
    settings = get_settings()
    digest = hashlib.sha256(settings.encryption_key.encode("utf-8")).digest()
    return digest


def encrypt_secret(plaintext: str) -> str:
    key = _aes_key()
    nonce = secrets.token_bytes(12)
    aes = AESGCM(key)
    ciphertext = aes.encrypt(nonce, plaintext.encode("utf-8"), None)
    return (nonce + ciphertext).hex()


def decrypt_secret(payload: str) -> str:
    raw = bytes.fromhex(payload)
    nonce, ciphertext = raw[:12], raw[12:]
    aes = AESGCM(_aes_key())
    return aes.decrypt(nonce, ciphertext, None).decode("utf-8")
