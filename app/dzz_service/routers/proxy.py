from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.dzz_service import service
from app.users_service.models import User

router = APIRouter(prefix="/dzz", tags=["dzz-tiles"])


@router.get("/tiles/{z}/{x}/{y}")
async def tiles(
    z: int,
    x: int,
    y: int,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    content, media = await service.fetch_tile(db, current, z, x, y)
    return Response(content=content, media_type=media)
