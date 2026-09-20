from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.dzz_service import service
from app.dzz_service.schemas import DzzConnectRequest
from app.users_service.models import User

router = APIRouter(prefix="/dzz", tags=["dzz"])


@router.post("/connect")
async def connect(
    payload: DzzConnectRequest,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await service.connect(db, current, payload.login, payload.password, payload.service_url)


@router.post("/check")
async def check(
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await service.check(db, current)


@router.post("/disconnect")
async def disconnect(
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await service.disconnect(db, current)
    return {"detail": "ok"}


@router.get("/status")
async def status(
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await service.status_payload(db, current)


@router.get("/wmts/capabilities")
async def capabilities(
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await service.wmts_capabilities(db, current)


@router.get("/regions")
async def regions(
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await service.regions(db, current)
