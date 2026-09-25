from __future__ import annotations

import hashlib
import json
import logging
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings

logger = logging.getLogger(__name__)

COOKIE_NAME = "dzz_sid"

_SESSIONS: dict[str, dict[str, Any]] = {}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _session_key() -> bytes:
    return hashlib.sha256(get_settings().secret_key.encode("utf-8")).digest()


def sessions_path() -> Path:
    return Path(get_settings().dzz_sessions_path)


def session_ttl() -> timedelta:
    return timedelta(hours=get_settings().dzz_session_ttl_hours)


def cookie_max_age() -> int:
    return int(session_ttl().total_seconds())


def _serialize(row: dict[str, Any]) -> dict[str, Any]:
    expires = row["expires_at"]
    if isinstance(expires, datetime):
        expires = expires.isoformat()
    return {
        "login": row.get("login") or "",
        "password": row.get("password") or "",
        "url": row.get("url") or "",
        "expires_at": expires,
    }


def _deserialize(row: dict[str, Any]) -> dict[str, Any] | None:
    raw_exp = row.get("expires_at")
    try:
        expires = datetime.fromisoformat(str(raw_exp))
    except ValueError:
        return None
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires <= _utcnow():
        return None
    return {
        "login": row.get("login") or "",
        "password": row.get("password") or "",
        "url": row.get("url") or "",
        "expires_at": expires,
    }


def load_dzz_sessions() -> None:
    path = sessions_path()
    if not path.is_file():
        return
    try:
        blob = path.read_bytes()
        if len(blob) < 13:
            return
        nonce, ciphertext = blob[:12], blob[12:]
        payload = AESGCM(_session_key()).decrypt(nonce, ciphertext, None)
        data = json.loads(payload.decode("utf-8"))
    except Exception:
        logger.warning("could not load dzz session file %s", path)
        return
    restored: dict[str, dict[str, Any]] = {}
    if isinstance(data, dict):
        for sid, row in data.items():
            if not isinstance(row, dict):
                continue
            parsed = _deserialize(row)
            if parsed:
                restored[str(sid)] = parsed
    _SESSIONS.clear()
    _SESSIONS.update(restored)


def save_dzz_sessions() -> None:
    path = sessions_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        sid: _serialize(row)
        for sid, row in _SESSIONS.items()
        if row.get("expires_at") and row["expires_at"] > _utcnow()
    }
    raw = json.dumps(payload).encode("utf-8")
    nonce = secrets.token_bytes(12)
    blob = nonce + AESGCM(_session_key()).encrypt(nonce, raw, None)
    path.write_bytes(blob)


def reset_sessions() -> None:
    _SESSIONS.clear()


def get_session(sid: str | None) -> dict[str, Any] | None:
    if not sid:
        return None
    row = _SESSIONS.get(sid)
    if row is None:
        return None
    expires = row.get("expires_at")
    if not isinstance(expires, datetime) or expires <= _utcnow():
        _SESSIONS.pop(sid, None)
        return None
    return row


def put_session(sid: str | None, login: str, password: str, url: str) -> str:
    token = sid if sid and sid in _SESSIONS else secrets.token_bytes(32).hex()
    _SESSIONS[token] = {
        "login": login,
        "password": password,
        "url": url,
        "expires_at": _utcnow() + session_ttl(),
    }
    save_dzz_sessions()
    return token


def delete_session(sid: str | None) -> None:
    if not sid:
        return
    if sid in _SESSIONS:
        _SESSIONS.pop(sid, None)
        save_dzz_sessions()
