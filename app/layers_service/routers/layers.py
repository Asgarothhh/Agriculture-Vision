from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.layers_service import service
from app.layers_service.schemas import LayerCreate, LayerUpdate, ObjectCreate, ObjectUpdate, MergeRequest
from app.users_service.models import User

router = APIRouter(prefix="/layers", tags=["layers"])
objects_router = APIRouter(tags=["objects"])


@router.get("/")
async def list_layers(
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    search: str | None = Query(default=None),
):
    return await service.list_layers(db, current, search)


@router.post("/")
async def create_layer(
    payload: LayerCreate,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await service.create_layer(db, current, payload)


@router.patch("/{layer_id}")
async def update_layer(
    layer_id: UUID,
    payload: LayerUpdate,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await service.update_layer(db, current, layer_id, payload)


@router.delete("/{layer_id}")
async def delete_layer(
    layer_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await service.delete_layer(db, current, layer_id)
    return {"detail": "ok"}


@router.get("/{layer_id}/objects")
async def list_objects(
    layer_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await service.list_layer_objects(db, current, layer_id)


@router.post("/{layer_id}/objects")
async def add_object(
    layer_id: UUID,
    payload: ObjectCreate,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await service.add_object(db, current, layer_id, payload)


@objects_router.get("/objects/{object_id}")
async def get_object(
    object_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    obj = await service.get_owned_object(db, current, object_id)
    return await service.object_payload(db, obj)


@objects_router.patch("/objects/{object_id}")
async def patch_object(
    object_id: UUID,
    payload: ObjectUpdate,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await service.update_object(db, current, object_id, payload)


@objects_router.delete("/objects/{object_id}")
async def delete_object(
    object_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await service.delete_object(db, current, object_id)
    return {"detail": "ok"}


@objects_router.post("/objects/merge")
async def merge_objects(
    payload: MergeRequest,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await service.merge_objects(db, current, payload)
