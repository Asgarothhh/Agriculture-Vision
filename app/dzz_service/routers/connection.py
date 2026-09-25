from __future__ import annotations

from fastapi import APIRouter, Request, Response

from app.dzz_service import service
from app.dzz_service.schemas import DzzConnectRequest, WmtsCapabilitiesRequest
from app.dzz_service.sessions import COOKIE_NAME, cookie_max_age

router = APIRouter(prefix="/dzz", tags=["dzz"])


def _set_dzz_cookie(response: Response, sid: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=sid,
        httponly=True,
        samesite="lax",
        max_age=cookie_max_age(),
        path="/",
    )


def _clear_dzz_cookie(response: Response) -> None:
    response.delete_cookie(key=COOKIE_NAME, path="/")


@router.post("/connect")
async def connect(payload: DzzConnectRequest, request: Request, response: Response):
    result = await service.connect(request, payload.login, payload.password, payload.service)
    _set_dzz_cookie(response, result.pop("sid"))
    return result


@router.post("/check")
async def check(request: Request):
    return await service.health_payload(request)


@router.get("/health")
async def health(request: Request):
    return await service.health_payload(request)


@router.post("/disconnect")
async def disconnect(request: Request, response: Response):
    service.disconnect(request)
    _clear_dzz_cookie(response)
    return {"detail": "ok"}


@router.get("/status")
async def status(request: Request):
    return service.status_payload(request)


@router.get("/wmts/capabilities")
async def capabilities_get(request: Request):
    return await service.wmts_capabilities_flat(request)


@router.post("/wmts/capabilities")
async def capabilities_post(request: Request, payload: WmtsCapabilitiesRequest | None = None):
    body = payload or WmtsCapabilitiesRequest()
    return await service.wmts_capabilities(request, body.url, body.login, body.password)


@router.get("/regions")
async def regions(request: Request):
    return await service.regions(request)


@router.get("/sites")
async def sites(request: Request):
    return await service.query_sites(request)
