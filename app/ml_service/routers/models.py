from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.ml_service.runtime import health as ml_health
from app.ml_service.models import ModelRegistry, ObjectClass
from app.users_service.models import User

router = APIRouter(tags=["models"])


@router.get("/models/")
async def list_models(
    _: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    rows = (await db.execute(select(ModelRegistry).order_by(ModelRegistry.id))).scalars().all()
    live = ml_health()
    loaded = {
        item.get("code")
        for item in live.get("models", [])
        if item.get("loaded")
    }
    return [
        {
            "id": row.id,
            "name": row.name,
            "code": row.code,
            "version": row.version,
            "task_type": row.task_type,
            "status": "loaded" if row.code in loaded else "unloaded",
        }
        for row in rows
    ]


@router.get("/models/health")
async def models_health(_: Annotated[User, Depends(get_current_user)]):
    payload = ml_health()
    status = payload.get("status") or "unavailable"
    if status not in {"ready", "unavailable"}:
        status = "ready" if status in {"ok", "healthy"} else "unavailable"
    return {"status": status, "models": payload.get("models") or []}


@router.get("/classes/")
async def list_classes(
    _: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    rows = (await db.execute(select(ObjectClass).order_by(ObjectClass.id))).scalars().all()
    return [
        {
            "id": row.id,
            "name": row.name,
            "geometry_type": row.geometry_type,
            "is_crop": row.is_crop,
        }
        for row in rows
    ]
