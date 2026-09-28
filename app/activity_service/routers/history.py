from __future__ import annotations

import json
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.activity_service import service
from app.core.database import get_db
from app.core.deps import Pagination, get_current_user
from app.core.ratelimit import limiter
from app.ml_service.postprocess import results_to_geojson
from app.users_service.models import User

router = APIRouter(prefix="/activity", tags=["activity"])

CLIENT_PAYLOAD_MAX_BYTES = 2048


class ClientEvent(BaseModel):
    """A UI event the server cannot observe itself (tool switch, undo, basemap change…)."""

    category: Literal["account", "map_tools", "export", "upload_processing"]
    action: str = Field(min_length=1, max_length=300)
    payload: dict[str, Any] | None = None

    @field_validator("action")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("action must not be blank")
        return value

    @field_validator("payload")
    @classmethod
    def _small_payload(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is not None and len(json.dumps(value, ensure_ascii=False)) > CLIENT_PAYLOAD_MAX_BYTES:
            raise ValueError("payload is too large")
        return value


@router.post("/", status_code=201)
@limiter.limit("120/minute")
async def add_event(
    request: Request,
    event: ClientEvent,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await service.log_event(
        db, current.id, event.category, event.action, {**(event.payload or {}), "source": "ui"}, commit=True
    )
    return {"detail": "ok"}


@router.get("/")
async def history(
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    pagination: Annotated[Pagination, Depends()],
    category: Annotated[list[str] | None, Query()] = None,
    q: str | None = None,
    order: Literal["newest", "oldest"] = "newest",
):
    return await service.list_activity(
        db,
        current,
        category=category,
        q=q,
        order=order,
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.get("/{task_id}/result")
async def download_result(
    task_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    task = await service.task_for_user(db, current, task_id)
    geojson = await results_to_geojson(db, task)
    payload = JSONResponse(geojson).body
    return Response(
        content=payload,
        media_type="application/geo+json",
        headers={"Content-Disposition": f'attachment; filename="task-{task_id}.geojson"'},
    )


@router.get("/{task_id}/open")
async def open_result(
    task_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    task = await service.task_for_user(db, current, task_id)
    return await results_to_geojson(db, task)
