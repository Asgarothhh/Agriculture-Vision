from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.dzz_service import service

router = APIRouter(prefix="/dzz", tags=["dzz-tiles"])


@router.get("/tiles/{z}/{x}/{y}")
async def tiles(z: int, x: int, y: int, request: Request):
    content, media = await service.fetch_tile(request, z, x, y)
    return Response(content=content, media_type=media)


@router.api_route("/{path:path}", methods=["GET", "HEAD", "POST"], include_in_schema=False)
async def proxy(path: str, request: Request):
    return await service.proxy_arcgis(request, path)
