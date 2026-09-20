from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.layers_service import service
from app.layers_service.schemas import ExportRequest
from app.users_service.models import User

router = APIRouter(prefix="/layers", tags=["import-export"])


@router.post("/import")
async def import_layer(
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(...),
):
    return await service.import_file(db, current, file)


@router.post("/export")
async def export_layers(
    payload: ExportRequest,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    content, media, filename = await service.export_layers(db, current, payload)
    return Response(
        content=content,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
