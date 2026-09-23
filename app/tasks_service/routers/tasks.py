from __future__ import annotations

import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import Pagination, get_current_user
from app.ml_service.postprocess import results_to_geojson
from app.tasks_service import service
from app.tasks_service.schemas import ToLayersRequest
from app.users_service.models import User

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("/")
async def create_task(
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(...),
    model: str = Form("segformer"),
    confidence: float = Form(0.5),
    aoi: str | None = Form(None),
    geo_bounds: str | None = Form(None),
):
    aoi_obj = json.loads(aoi) if aoi else None
    try:
        bounds_obj = json.loads(geo_bounds) if geo_bounds else None
    except json.JSONDecodeError as exc:
        from fastapi import HTTPException

        raise HTTPException(400, "geo_bounds must be JSON") from exc
    task = await service.create_task(db, current, file, model, confidence, aoi_obj, bounds_obj)
    return {"task_id": task.id, **service.task_to_dict(task)}


@router.get("/")
async def list_tasks(
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    pagination: Annotated[Pagination, Depends()],
    status: str | None = None,
):
    return await service.list_tasks(
        db, current, status_filter=status, limit=pagination.limit, offset=pagination.offset
    )


@router.get("/{task_id}")
async def get_task(
    task_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    task = await service.get_task(db, current, task_id)
    return service.task_to_dict(task)


@router.get("/{task_id}/result")
async def task_result(
    task_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    task = await service.get_task(db, current, task_id)
    if task.status != "COMPLETED":
        from fastapi import HTTPException

        raise HTTPException(409, "Task is not completed")
    return await results_to_geojson(db, task)


@router.post("/{task_id}/to-layers")
async def to_layers(
    task_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    payload: ToLayersRequest | None = None,
):
    task = await service.get_task(db, current, task_id)
    class_ids = payload.class_ids if payload else None
    return await service.publish_to_layers(db, current, task, class_ids)


@router.delete("/{task_id}")
async def delete_task(
    task_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await service.delete_task(db, current, task_id)
    return {"detail": "ok"}
