from __future__ import annotations

import logging
import re
import struct
from datetime import UTC, datetime
from typing import Any
from xml.etree import ElementTree as ET

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import decrypt_secret, encrypt_secret
from app.dzz_service.models import DzzConnection
from app.users_service.models import User

logger = logging.getLogger(__name__)

# #region agent log
_DEBUG_LOG = "/home/asgaroth/Projects/Agriculture-Vision/Agriculture-Vision/.cursor/debug-14c4e4.log"


def _dbg(hypothesis_id: str, message: str, data: dict[str, Any]) -> None:
    try:
        import json
        import time

        with open(_DEBUG_LOG, "a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "sessionId": "14c4e4",
                        "hypothesisId": hypothesis_id,
                        "location": "app/dzz_service/service.py",
                        "message": message,
                        "data": data,
                        "timestamp": int(time.time() * 1000),
                    },
                    default=str,
                )
                + "\n"
            )
    except Exception:
        pass


# #endregion

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

WEB_MERCATOR_ORIGIN = 20037508.342789244
GOOGLE_Z0_RES = 156543.03392804097
PNG_MAGIC = b"\x89PNG"
JPEG_MAGIC = b"\xff\xd8"
WEBP_MAGIC = b"RIFF"
ORTHO_DEFAULT = (
    "https://www.dzz.by/arcgis/rest/services/georesursDDZ/Belarus_web_mercator_all/ImageServer"
)
DZZ_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Referer": "https://www.dzz.by/",
}
_lod_cache: dict[str, list[dict[str, Any]]] = {}

IMAGE_SERVER_ROOT_RE = re.compile(
    r"(https?://[^/]+/arcgis/rest/services/[^/]+/[^/]+/ImageServer)",
    re.IGNORECASE,
)
TILE_TEMPLATE_RE = re.compile(
    r"/tile/\{[^/]+\}/\{[^/]+\}/\{[^/]+\}/?$",
    re.IGNORECASE,
)
XYZ_TEMPLATE_RE = re.compile(
    r"/\{z\}/\{[xy]\}/\{[xy]\}(?:\.png)?/?$",
    re.IGNORECASE,
)


def _http_auth(login: str, password: str) -> tuple[str, str] | None:
    if login or password:
        return login, password
    return None


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _image_server_root(url: str) -> str | None:
    match = IMAGE_SERVER_ROOT_RE.search(url or "")
    if match:
        return match.group(1).rstrip("/")
    stripped = (url or "").rstrip("/")
    if re.search(r"/ImageServer$", stripped, re.IGNORECASE):
        return stripped
    return None


def normalize_service_url(url: str | None) -> str:
    raw = (url or "").strip()
    raw = TILE_TEMPLATE_RE.sub("", raw)
    raw = XYZ_TEMPLATE_RE.sub("", raw)
    raw = raw.rstrip("/")
    root = _image_server_root(raw)
    return root or raw


def effective_service_url(url: str | None) -> str:
    """Polya_all is a field mask, not nationwide ortho — empty/white in cities."""
    root = normalize_service_url(url)
    if "/Polya_all/ImageServer" in (root or ""):
        return root.replace("/Polya_all/ImageServer", "/Belarus_web_mercator_all/ImageServer")
    return root or ORTHO_DEFAULT


def _host_variants(url: str) -> list[str]:
    variants = [url]
    replacements = (
        ("https://www.dzz.by", "https://geodzz.by"),
        ("https://dzz.by", "https://geodzz.by"),
        ("https://www.dzz.by", "https://www.geodzz.by"),
        ("https://geodzz.by", "https://www.dzz.by"),
    )
    for src, dst in replacements:
        if src in url:
            variants.append(url.replace(src, dst, 1))
    seen: set[str] = set()
    unique: list[str] = []
    for item in variants:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def _probe_url(url: str) -> str:
    root = effective_service_url(url)
    if root and re.search(r"ImageServer$", root, re.IGNORECASE):
        return f"{root}?f=json"
    return root


def _google_lod(lods: list[dict[str, Any]], z: int) -> int | None:
    if not lods:
        return z
    target = GOOGLE_Z0_RES / (2 ** max(z, 0))
    best = min(lods, key=lambda item: abs(float(item.get("resolution") or 0) - target))
    res = float(best.get("resolution") or 0)
    if res <= 0 or abs(res - target) / target > 0.25:
        return None
    return int(best["level"])


def _tile_bbox_3857(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    n = 2 ** max(z, 0)
    size = (WEB_MERCATOR_ORIGIN * 2) / n
    minx = -WEB_MERCATOR_ORIGIN + x * size
    maxy = WEB_MERCATOR_ORIGIN - y * size
    return minx, maxy - size, minx + size, maxy


def _export_image_url(root: str, z: int, x: int, y: int, fmt: str = "jpg") -> str:
    minx, miny, maxx, maxy = _tile_bbox_3857(z, x, y)
    return (
        f"{root}/exportImage?bbox={minx},{miny},{maxx},{maxy}"
        f"&bboxSR=3857&imageSR=3857&size=256,256&format={fmt}&f=image"
    )


def _tile_urls(base: str, z: int, x: int, y: int, lod: int | None = None) -> list[str]:
    base = effective_service_url(base)
    tile_z = z if lod is None else lod
    urls: list[str] = []
    for root_candidate in _host_variants(base):
        root = _image_server_root(root_candidate)
        if root:
            urls.extend(
                [
                    f"{root}/tile/{tile_z}/{y}/{x}",
                    _export_image_url(root, z, x, y, "jpg"),
                    f"{root}/tile/{tile_z}/{x}/{y}",
                    _export_image_url(root, z, x, y, "png"),
                ]
            )
        urls.extend(
            [
                f"{root_candidate}/{z}/{x}/{y}.png",
                f"{root_candidate}/{z}/{x}/{y}",
                f"{root_candidate}/{z}/{y}/{x}.png",
                f"{root_candidate}/{z}/{y}/{x}",
                f"{root_candidate}/wmts/{z}/{x}/{y}.png",
            ]
        )
    seen: set[str] = set()
    unique: list[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique


def _looks_like_image(content: bytes, content_type: str) -> bool:
    if content == TRANSPARENT_PNG or len(content) < 400:
        return False
    if content.startswith(PNG_MAGIC) and len(content) >= 24:
        width, height = struct.unpack(">II", content[16:24])
        if width <= 1 and height <= 1:
            return False
        if len(content) < 1500:
            return False
    if content.startswith(JPEG_MAGIC) and len(content) < 1500:
        return False
    lowered = (content_type or "").split(";")[0].strip().lower()
    if lowered.startswith("application/json") or lowered.startswith("text/"):
        return False
    if content.startswith(PNG_MAGIC) or content.startswith(JPEG_MAGIC) or content.startswith(WEBP_MAGIC):
        return True
    return lowered.startswith("image/") and not lowered.endswith("json")


async def _owned_connection(db: AsyncSession, user: User) -> DzzConnection | None:
    return (
        await db.execute(select(DzzConnection).where(DzzConnection.user_id == user.id))
    ).scalar_one_or_none()


async def probe_connection(url: str, login: str, password: str) -> str:
    last = "unavailable"
    try:
        async with httpx.AsyncClient(
            timeout=10.0, follow_redirects=True, headers=DZZ_HTTP_HEADERS
        ) as client:
            for candidate in _host_variants(effective_service_url(url)):
                target = _probe_url(candidate)
                if not target:
                    continue
                try:
                    auth = _http_auth(login, password)
                    response = await client.get(target, auth=auth)
                except httpx.HTTPError:
                    last = "unavailable"
                    continue
                if response.status_code in {401, 403}:
                    return "bad_credentials"
                if response.status_code >= 400:
                    last = "unavailable"
                    continue
                content_type = response.headers.get("content-type", "")
                if "json" in content_type.lower():
                    try:
                        payload = response.json()
                    except ValueError:
                        return "online"
                    error = payload.get("error") if isinstance(payload, dict) else None
                    if isinstance(error, dict):
                        code = int(error.get("code") or 0)
                        if code in {401, 403, 498, 499}:
                            return "bad_credentials"
                        last = "unavailable"
                        continue
                return "online"
    except httpx.HTTPError:
        return "unavailable"
    return last


async def connect(
    db: AsyncSession,
    user: User,
    login: str,
    password: str,
    service_url: str | None,
) -> dict[str, Any]:
    settings = get_settings()
    url = effective_service_url(service_url or settings.dzz_default_url)
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


async def fetch_tile(db: AsyncSession, user: User, z: int, x: int, y: int) -> tuple[bytes, str]:
    row = await _owned_connection(db, user)
    if row is None or not row.is_active:
        # #region agent log
        _dbg("A", "fetch_tile no connection", {"z": z, "x": x, "y": y, "has_row": row is not None})
        # #endregion
        return TRANSPARENT_PNG, "image/png"

    cache_key = f"dzz:v2:{user.id}:{z}:{x}:{y}"
    cached = await _redis_get(cache_key)
    if cached and _looks_like_image(cached, "image/jpeg"):
        media = "image/jpeg" if cached.startswith(JPEG_MAGIC) else "image/png"
        # #region agent log
        _dbg("E", "fetch_tile cache hit", {"z": z, "x": x, "y": y, "bytes": len(cached), "media": media})
        # #endregion
        return cached, media

    login, password = _auth_tuple(row)
    root = effective_service_url(row.service_url)
    auth = _http_auth(login, password)
    # #region agent log
    _dbg(
        "B",
        "fetch_tile upstream start",
        {"z": z, "x": x, "y": y, "root": root[-80:], "stored": (row.service_url or "")[-80:], "has_auth": bool(auth)},
    )
    # #endregion
    async with httpx.AsyncClient(
        timeout=20.0, follow_redirects=True, headers=DZZ_HTTP_HEADERS
    ) as client:
        lods = await _service_lods(client, root, auth)
        lod = _google_lod(lods, z)
        for url in _tile_urls(root, z, x, y, lod):
            try:
                response = await client.get(url, auth=auth)
            except httpx.HTTPError:
                continue
            if response.status_code in {204, 404, 520}:
                continue
            if response.status_code == 200 and response.content:
                content_type = response.headers.get("content-type", "image/jpeg")
                if _looks_like_image(response.content, content_type):
                    media = content_type.split(";")[0].strip()
                    if not media.startswith("image/"):
                        media = "image/jpeg" if response.content.startswith(JPEG_MAGIC) else "image/png"
                    await _redis_set(cache_key, response.content)
                    # #region agent log
                    _dbg(
                        "B",
                        "fetch_tile upstream ok",
                        {
                            "z": z,
                            "x": x,
                            "y": y,
                            "lod": lod,
                            "bytes": len(response.content),
                            "media": media,
                            "url": url[-90:],
                        },
                    )
                    # #endregion
                    return response.content, media
                logger.info(
                    "dzz tile skipped %s status=%s content-type=%s bytes=%s",
                    url,
                    response.status_code,
                    content_type,
                    len(response.content),
                )
            elif response.status_code not in {401, 403}:
                logger.info("dzz tile miss %s status=%s", url, response.status_code)
    # #region agent log
    _dbg("B", "fetch_tile fallback transparent", {"z": z, "x": x, "y": y, "lod": lod, "root": root[-80:]})
    # #endregion
    return TRANSPARENT_PNG, "image/png"


async def _service_lods(
    client: httpx.AsyncClient, root: str, auth: tuple[str, str] | None
) -> list[dict[str, Any]]:
    cached = _lod_cache.get(root)
    if cached is not None:
        return cached
    try:
        response = await client.get(f"{root}?f=json", auth=auth)
        payload = response.json() if response.status_code == 200 else {}
        lods = (payload.get("tileInfo") or {}).get("lods") or []
    except Exception:
        lods = []
    _lod_cache[root] = lods
    return lods


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
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers=DZZ_HTTP_HEADERS) as client:
        for url in urls:
            try:
                response = await client.get(url, auth=_http_auth(login, password))
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
