from __future__ import annotations

from fastapi import APIRouter, Request

from app.dzz_service import service
from app.dzz_service.schemas import WmtsCapabilitiesRequest

router = APIRouter(prefix="/wmts", tags=["wmts"])


@router.post("/capabilities")
async def capabilities(request: Request, payload: WmtsCapabilitiesRequest):
    return await service.wmts_capabilities(request, payload.url, payload.login, payload.password)
