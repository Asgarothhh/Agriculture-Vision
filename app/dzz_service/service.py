from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID
from xml.etree import ElementTree as ET

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import decrypt_secret, encrypt_secret
from app.dzz_service.models import DzzConnection
from app.users_service.models import User

TRANSPARENT_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)

DEFAULT_REGIONS = [
    ["Минская область", 53.9, 27.55],
    ["Брестская область", 52.1, 23.7],
    ["Гомельская область", 52.44, 30.99],
    ["Гродненская область", 53.68, 23.83],
    ["Витебская область", 55.19, 30.17],
    ["Могилёвская область", 53.9, 30.34],
]


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def _owned_connection(db: AsyncSession, user: User) -> DzzConnection | None:
    return (
        await db.execute(select(DzzConnection).where(DzzConnection.user_id == user.id))
    ).scalar_one_or_none()


async def probe_connection(url: str, login: str, password: str) -> str:
    if not url:
        return "unavailable"
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.get(url, auth=(login, password))
            if response.status_code in {401, 403}:
                return "bad_credentials"
            if response.status_code >= 500:
                return "unavailable"
            return "online"
    except httpx.HTTPError:
        return "unavailable"


async def connect(
    db: AsyncSession,
    user: User,
    login: str,
    password: str,
    service_url: str | None,
) -> dict[str, Any]:
    settings = get_settings()
    url = (service_url or settings.dzz_default_url).rstrip("/")
    status_value = await probe_connection(url, login, password)
    if status_value == "bad_credentials":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Неверные учётные данные dzz.by")
    if status_value == "unavailable":
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="dzz.by недоступен")

    row = await _owned_connection(db, user)
    if row is None:
        row = DzzConnection(user_id=user.id, service_url=url)
        db.add(row)
    row.login_encrypted = encrypt_secret(login)
    row.password_encrypted = encrypt_secret(password)
    row.service_url = url
    row.is_active = True
    row.last_status = status_value
    row.last_check_at = _utcnow()
    await db.commit()
    return {"status": status_value, "service_url": url}


async def check(db: AsyncSession, user: User) -> dict[str, Any]:
    row = await _owned_connection(db, user)
    if row is None or not row.is_active:
        return {"status": "unavailable"}
    status_value = await probe_connection(
        row.service_url,
        decrypt_secret(row.login_encrypted),
        decrypt_secret(row.password_encrypted),
    )
    row.last_status = status_value
    row.last_check_at = _utcnow()
    await db.commit()
    return {"status": status_value}


async def disconnect(db: AsyncSession, user: User) -> None:
    row = await _owned_connection(db, user)
    if row:
        await db.delete(row)
        await db.commit()


async def status_payload(db: AsyncSession, user: User) -> dict[str, Any]:
    row = await _owned_connection(db, user)
    if row is None:
        return {"status": "unavailable", "connected": False}
    return {
        "status": row.last_status,
        "connected": row.is_active,
        "last_check_at": row.last_check_at,
        "service_url": row.service_url,
    }


def _auth_tuple(row: DzzConnection) -> tuple[str, str]:
    return decrypt_secret(row.login_encrypted), decrypt_secret(row.password_encrypted)


def _tile_urls(base: str, z: int, x: int, y: int) -> list[str]:
    base = base.rstrip("/")
    return [
        f"{base}/{z}/{x}/{y}.png",
        f"{base}/{z}/{x}/{y}",
        f"{base}/{z}/{y}/{x}.png",
        f"{base}/{z}/{y}/{x}",
        f"{base}/wmts/{z}/{x}/{y}.png",
    ]


async def fetch_tile(db: AsyncSession, user: User, z: int, x: int, y: int) -> tuple[bytes, str]:
    row = await _owned_connection(db, user)
    if row is None or not row.is_active:
        return TRANSPARENT_PNG, "image/png"

    cache_key = f"dzz:{user.id}:{z}:{x}:{y}"
    cached = await _redis_get(cache_key)
    if cached:
        return cached, "image/png"

    login, password = _auth_tuple(row)
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        for url in _tile_urls(row.service_url, z, x, y):
            try:
                response = await client.get(url, auth=(login, password))
            except httpx.HTTPError:
                continue
            if response.status_code in {204, 404}:
                await _redis_set(cache_key, TRANSPARENT_PNG)
                return TRANSPARENT_PNG, "image/png"
            if response.status_code == 200 and response.content:
                content_type = response.headers.get("content-type", "image/png")
                if content_type.startswith("image/"):
                    await _redis_set(cache_key, response.content)
                    return response.content, content_type
    await _redis_set(cache_key, TRANSPARENT_PNG)
    return TRANSPARENT_PNG, "image/png"


async def _redis_get(key: str) -> bytes | None:
    try:
        import redis.asyncio as redis

        client = redis.from_url(get_settings().redis_url)
        try:
            return await client.get(key)
        finally:
            await client.aclose()
    except Exception:
        return None


async def _redis_set(key: str, value: bytes, ttl: int = 3600) -> None:
    try:
        import redis.asyncio as redis

        client = redis.from_url(get_settings().redis_url)
        try:
            await client.setex(key, ttl, value)
        finally:
            await client.aclose()
    except Exception:
        return


async def wmts_capabilities(db: AsyncSession, user: User) -> list[dict[str, str]]:
    row = await _owned_connection(db, user)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="dzz connection not found")
    login, password = _auth_tuple(row)
    urls = [
        f"{row.service_url.rstrip('/')}/WMTSCapabilities.xml",
        f"{row.service_url.rstrip('/')}/wmts/1.0.0/WMTSCapabilities.xml",
        f"{row.service_url.rstrip('/')}/geoserver/gwc/service/wmts?REQUEST=GetCapabilities",
    ]
    xml_text = None
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        for url in urls:
            try:
                response = await client.get(url, auth=(login, password))
            except httpx.HTTPError:
                continue
            if response.status_code == 200 and response.text:
                xml_text = response.text
                break
    if not xml_text:
        return []
    return _parse_wmts(xml_text)


def _parse_wmts(xml_text: str) -> list[dict[str, str]]:
    ns = {
        "wmts": "http://www.opengis.net/wmts/1.0",
        "ows": "http://www.opengis.net/ows/1.1",
    }
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    items: list[dict[str, str]] = []
    layers = root.findall(".//{http://www.opengis.net/wmts/1.0}Layer") or root.findall(".//Layer")
    for layer in layers:
        ident = (
            (layer.findtext("{http://www.opengis.net/ows/1.1}Identifier") or layer.findtext("Identifier") or "")
        )
        tilematrix = (
            layer.findtext(".//{http://www.opengis.net/wmts/1.0}TileMatrixSet")
            or layer.findtext(".//TileMatrixSet")
            or ""
        )
        style = layer.findtext(".//{http://www.opengis.net/wmts/1.0}Style/{http://www.opengis.net/ows/1.1}Identifier")
        if not style:
            style = layer.findtext(".//Style/Identifier") or "default"
        if ident:
            items.append({"layer": ident, "tilematrix": tilematrix, "style": style})
    return items


async def regions(db: AsyncSession, user: User) -> list[list]:
    caps = []
    try:
        caps = await wmts_capabilities(db, user)
    except HTTPException:
        caps = []
    if not caps:
        return DEFAULT_REGIONS
    result = []
    for idx, item in enumerate(caps):
        if idx < len(DEFAULT_REGIONS):
            result.append([item["layer"], DEFAULT_REGIONS[idx][1], DEFAULT_REGIONS[idx][2]])
        else:
            result.append([item["layer"], 53.9, 27.55])
    return result
