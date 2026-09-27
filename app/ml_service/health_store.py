"""Model status shared between the Celery worker (loads weights) and the API (reports them).

The API pod does not load torch/weights; the worker publishes ``ModelRuntime.health()``
to Redis after ``load_models()`` and the API reads it back for ``/models/health``.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

import redis

from app.core.config import get_settings
from app.ml_service.runtime import runtime

logger = logging.getLogger(__name__)

KEY = "agrovision:ml:health"
PING_TIMEOUT_S = 1.0


def _client() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, socket_timeout=2, socket_connect_timeout=2)


def publish_health(payload: dict[str, Any]) -> None:
    data = {**payload, "updated_at": datetime.now(UTC).isoformat()}
    _client().set(KEY, json.dumps(data))


def clear_health() -> None:
    _client().delete(KEY)


def read_health() -> dict[str, Any] | None:
    try:
        raw = _client().get(KEY)
    except redis.RedisError as exc:
        logger.warning("ML health read failed: %s", exc)
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        logger.warning("ML health payload in Redis is not valid JSON")
        return None


def _worker_alive() -> bool:
    try:
        from app.core.celery_app import celery_app

        return bool(celery_app.control.ping(timeout=PING_TIMEOUT_S, limit=1))
    except Exception as exc:
        logger.warning("Celery ping failed: %s", exc)
        return False


def _unavailable(base: dict[str, Any], error: str) -> dict[str, Any]:
    models = [{**item, "loaded": False, "error": error} for item in base.get("models") or []]
    return {"status": "unavailable", "models": models}


def get_ml_health() -> dict[str, Any]:
    local = runtime.health()
    if local.get("status") == "ready":
        return local
    remote = read_health()
    if remote is None:
        return _unavailable(local, "ML worker has not reported model status")
    if not _worker_alive():
        return _unavailable(remote, "ML worker offline")
    return {"status": remote.get("status") or "unavailable", "models": remote.get("models") or []}
