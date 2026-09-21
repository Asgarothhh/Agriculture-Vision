from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.layers_service import service
from app.layers_service.models import Folder
from app.layers_service.schemas import FolderCreate, FolderItems, FolderUpdate
from app.users_service.models import User

router = APIRouter(prefix="/folders", tags=["folders"])


@router.get("/")
async def list_folders(
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    rows = (
        await db.execute(select(Folder).where(Folder.user_id == current.id).order_by(Folder.created_at))
    ).scalars().all()
    return [
        {"id": f.id, "name": f.name, "is_visible": f.is_visible, "created_at": f.created_at}
        for f in rows
    ]


@router.post("/")
async def create_folder(
    payload: FolderCreate,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    folder = await service.create_folder(db, current, payload)
    return {"id": folder.id, "name": folder.name, "is_visible": folder.is_visible, "created_at": folder.created_at}


@router.patch("/{folder_id}")
async def update_folder(
    folder_id: UUID,
    payload: FolderUpdate,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    folder = await service.update_folder(db, current, folder_id, payload)
    return {"id": folder.id, "name": folder.name, "is_visible": folder.is_visible, "created_at": folder.created_at}


@router.delete("/{folder_id}")
async def delete_folder(
    folder_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await service.delete_folder(db, current, folder_id)
    return {"detail": "ok"}


@router.post("/{folder_id}/items")
async def move_items(
    folder_id: UUID,
    payload: FolderItems,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await service.move_folder_item(db, current, folder_id, payload)
