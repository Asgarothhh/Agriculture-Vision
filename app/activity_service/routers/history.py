from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.activity_service import service
from app.core.database import get_db
from app.core.deps import Pagination, get_current_user
from app.ml_service.postprocess import results_to_geojson
from app.users_service.models import User

router = APIRouter(prefix="/activity", tags=["activity"])


@router.get("/")
async def history(
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    pagination: Annotated[Pagination, Depends()],
    category: str | None = None,
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
