from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import HTTPException, Request, status
from fastapi.responses import Response

from app.core.config import get_settings
from app.dzz_service.sessions import (
    COOKIE_NAME,
    delete_session,
    get_session,
    put_session,
)
from app.dzz_service.wmts import (
    parse_wmts_capabilities,
    parse_wmts_layers_flat,
    pick_suggested_wmts,
    resolve_wmts_capabilities_url,
)

logger = logging.getLogger(__name__)

TRANSPARENT_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)

DZZ_UPSTREAM = "https://www.dzz.by"
DZZ_ALLOWED_HOSTS = {"dzz.by", "www.dzz.by", "geodzz.by", "www.geodzz.by"}
DZZ_DEFAULT_SERVICE = (
    "https://www.dzz.by/arcgis/rest/services/georesursDDZ/Polya_all/ImageServer"
)
DZZ_CACHE_MIN_Z = 10
DZZ_CACHE_MAX_Z = 14
DZZ_Z_OFFSET = 8
WEB_MERCATOR_ORIGIN = 20037508.342789244
WMTS_MAX_BYTES = int(2.5 * 1024 * 1024)
DZZ_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Referer": "https://www.dzz.by/",
}
DZZ_HOST_RE = re.compile(r"^(?:www\.)?(?:geo)?dzz\.by$", re.IGNORECASE)
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
WMTS_CAPS_RE = re.compile(
    r"/WMTS(?:/1\.0\.0)?/WMTSCapabilities\.xml.*$",
    re.IGNORECASE,
)

STATUS_ONLINE = "online"
STATUS_BAD_CREDENTIALS = "bad_credentials"
STATUS_UNAVAILABLE = "unavailable"


def _settings_default_url() -> str:
    return get_settings().dzz_default_url or DZZ_DEFAULT_SERVICE


def _is_allowed_host(hostname: str | None) -> bool:
    host = (hostname or "").strip().lower()
    return host in DZZ_ALLOWED_HOSTS or bool(DZZ_HOST_RE.match(host))


def looks_like_json(content_type: str, body: bytes) -> bool:
    lowered = (content_type or "").split(";")[0].strip().lower()
    if "json" in lowered:
        return True
    stripped = body.lstrip()[:1]
    return stripped in {b"{", b"["}


def classify_upstream(status_code: int, content_type: str, body: bytes) -> str:
    if status_code in {401, 403}:
        if looks_like_json(content_type, body):
            return STATUS_BAD_CREDENTIALS
        return STATUS_UNAVAILABLE
    if status_code >= 400:
        return STATUS_UNAVAILABLE
    if looks_like_json(content_type, body):
        try:
            import json

            payload = json.loads(body.decode("utf-8", errors="ignore") or "null")
        except ValueError:
            return STATUS_ONLINE
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            code = int(error.get("code") or 0)
            if code in {401, 403, 498, 499}:
                return STATUS_BAD_CREDENTIALS
            return STATUS_UNAVAILABLE
    return STATUS_ONLINE


def normalize_service_url(url: str | None) -> str:
    raw = (url or "").strip()
    raw = WMTS_CAPS_RE.sub("", raw)
    raw = TILE_TEMPLATE_RE.sub("", raw)
    raw = XYZ_TEMPLATE_RE.sub("", raw)
    raw = raw.rstrip("/")
    match = IMAGE_SERVER_ROOT_RE.search(raw)
    if match:
        return match.group(1).rstrip("/")
    if re.search(r"/ImageServer$", raw, re.IGNORECASE):
        return raw
    return raw


def resolve_dzz_service_root(url: str | None) -> str:
    root = normalize_service_url(url or _settings_default_url())
    parsed = urlparse(root)
    if parsed.scheme not in {"http", "https"} or not _is_allowed_host(parsed.hostname):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="URL должен указывать на ImageServer dzz.by",
        )
    if not re.search(r"/ImageServer$", root, re.IGNORECASE):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="URL должен указывать на ArcGIS ImageServer",
        )
    return root


def _tile_bbox_3857(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    n = 2 ** max(z, 0)
    size = (WEB_MERCATOR_ORIGIN * 2) / n
    minx = -WEB_MERCATOR_ORIGIN + x * size
    maxy = WEB_MERCATOR_ORIGIN - y * size
    return minx, maxy - size, minx + size, maxy


def dzz_export_image_url(root: str, z: int, x: int, y: int, fmt: str = "jpg") -> str:
    minx, miny, maxx, maxy = _tile_bbox_3857(z, x, y)
    return (
        f"{root}/exportImage?bbox={minx},{miny},{maxx},{maxy}"
        f"&bboxSR=3857&imageSR=3857&size=256,256&format={fmt}&f=image"
    )


def image_server_tile_url(root: str, z: int, x: int, y: int) -> str:
    if DZZ_CACHE_MIN_Z <= z <= DZZ_CACHE_MAX_Z:
        return f"{root}/tile/{z - DZZ_Z_OFFSET}/{y}/{x}"
    return dzz_export_image_url(root, z, x, y)


def _auth_tuple(login: str, password: str) -> tuple[str, str] | None:
    if login or password:
        return login, password
    return None


def _session_from_request(request: Request) -> dict[str, Any] | None:
    return get_session(request.cookies.get(COOKIE_NAME))


def _require_session(request: Request) -> dict[str, Any]:
    row = _session_from_request(request)
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Нет сессии dzz.by")
    return row


def _origin_of(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _assert_dzz_origin(url: str) -> None:
    parsed = urlparse(url)
    if not _is_allowed_host(parsed.hostname):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="host is not allowed")


async def fetch_dzz_upstream(
    client: httpx.AsyncClient,
    url: str,
    auth: tuple[str, str] | None,
    method: str = "GET",
    **kwargs: Any,
) -> httpx.Response:
    last_error: Exception | None = None
    response: httpx.Response | None = None
    for attempt in range(3):
        try:
            response = await client.request(method, url, auth=auth, **kwargs)
        except httpx.HTTPError as exc:
            last_error = exc
            await asyncio.sleep(0.4 * (attempt + 1))
            continue
        if response.status_code >= 500 or response.status_code == 520:
            if attempt < 2:
                await asyncio.sleep(0.4 * (attempt + 1))
                continue
        return response
    if response is not None:
        return response
    raise last_error or httpx.HTTPError("dzz.by unavailable")


async def probe_dzz_service(login: str, password: str, root: str) -> str:
    target = f"{root}?f=json"
    try:
        async with httpx.AsyncClient(
            timeout=10.0, follow_redirects=True, headers=DZZ_HTTP_HEADERS
        ) as client:
            try:
                response = await fetch_dzz_upstream(
                    client, target, _auth_tuple(login, password)
                )
            except httpx.HTTPError:
                return STATUS_UNAVAILABLE
            return classify_upstream(
                response.status_code,
                response.headers.get("content-type", ""),
                response.content or b"",
            )
    except httpx.HTTPError:
        return STATUS_UNAVAILABLE


async def connect(request: Request, login: str, password: str, service_url: str | None) -> dict[str, Any]:
    root = resolve_dzz_service_root(service_url or _settings_default_url())
    status_value = await probe_dzz_service(login, password, root)
    if status_value == STATUS_BAD_CREDENTIALS:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Неверные учётные данные dzz.by")
    if status_value == STATUS_UNAVAILABLE:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="dzz.by недоступен")
    sid = put_session(request.cookies.get(COOKIE_NAME), login, password, root)
    return {"status": status_value, "service_url": root, "url": root, "sid": sid, "connected": True}


def status_payload(request: Request) -> dict[str, Any]:
    row = _session_from_request(request)
    if row is None:
        return {"status": STATUS_UNAVAILABLE, "connected": False}
    return {
        "status": STATUS_ONLINE,
        "connected": True,
        "service_url": row.get("url"),
        "url": row.get("url"),
    }


async def health_payload(request: Request) -> dict[str, Any]:
    row = _session_from_request(request)
    if row is None:
        return {"status": STATUS_UNAVAILABLE, "connected": False}
    status_value = await probe_dzz_service(row["login"], row["password"], row["url"])
    return {
        "status": status_value,
        "connected": status_value == STATUS_ONLINE,
        "service_url": row.get("url"),
        "url": row.get("url"),
    }


def disconnect(request: Request) -> None:
    delete_session(request.cookies.get(COOKIE_NAME))


def _proxy_target(session_url: str, path: str, query: str) -> str:
    origin = _origin_of(session_url) or DZZ_UPSTREAM
    _assert_dzz_origin(origin)
    suffix = path if path.startswith("/") else f"/{path}"
    target = urljoin(origin + "/", suffix.lstrip("/"))
    parsed = urlparse(target)
    if parsed.path.startswith("/arcgis/") is False:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="path must start with /arcgis/")
    _assert_dzz_origin(target)
    if origin.rstrip("/") != _origin_of(target):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="origin mismatch")
    if query:
        return f"{target}?{query}" if "?" not in target else f"{target}&{query}"
    return target


async def proxy_arcgis(request: Request, path: str) -> Response:
    row = _require_session(request)
    target = _proxy_target(row["url"], path, request.url.query)
    auth = _auth_tuple(row["login"], row["password"])
    try:
        async with httpx.AsyncClient(
            timeout=12.0, follow_redirects=True, headers=DZZ_HTTP_HEADERS
        ) as client:
            upstream = await fetch_dzz_upstream(
                client,
                target,
                auth,
                method=request.method if request.method in {"GET", "HEAD", "POST"} else "GET",
                content=await request.body() if request.method == "POST" else None,
            )
    except httpx.HTTPError as exc:
        logger.info("dzz proxy unavailable %s: %s", target, exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="dzz.by недоступен") from exc

    kind = classify_upstream(
        upstream.status_code,
        upstream.headers.get("content-type", ""),
        upstream.content or b"",
    )
    if kind == STATUS_BAD_CREDENTIALS:
        return Response(
            content=upstream.content,
            status_code=401,
            media_type=upstream.headers.get("content-type", "application/json"),
        )
    if kind == STATUS_UNAVAILABLE and upstream.status_code in {401, 403}:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="dzz.by недоступен")

    media = upstream.headers.get("content-type") or "application/octet-stream"
    return Response(content=upstream.content, status_code=upstream.status_code, media_type=media)


async def fetch_tile(request: Request, z: int, x: int, y: int) -> tuple[bytes, str]:
    row = _session_from_request(request)
    if row is None:
        return TRANSPARENT_PNG, "image/png"
    root = row["url"]
    url = image_server_tile_url(root, z, x, y)
    parsed = urlparse(url)
    path = parsed.path.lstrip("/")
    query = parsed.query
    # Reuse proxy validation without requiring a second hop through FastAPI.
    dummy_path = path
    target = _proxy_target(root, dummy_path, query)
    auth = _auth_tuple(row["login"], row["password"])
    try:
        async with httpx.AsyncClient(
            timeout=12.0, follow_redirects=True, headers=DZZ_HTTP_HEADERS
        ) as client:
            response = await fetch_dzz_upstream(client, target, auth)
    except httpx.HTTPError:
        return TRANSPARENT_PNG, "image/png"
    if response.status_code == 200 and response.content:
        media = response.headers.get("content-type", "image/jpeg").split(";")[0].strip()
        if not media.startswith("image/"):
            media = "image/jpeg"
        return response.content, media
    return TRANSPARENT_PNG, "image/png"


def _is_dzz_url(url: str) -> bool:
    try:
        return _is_allowed_host(urlparse(url).hostname)
    except Exception:
        return False


async def _download_wmts_xml(url: str, login: str, password: str) -> str:
    dzz_source = _is_dzz_url(url)
    if dzz_source:
        _assert_dzz_origin(url)
    async with httpx.AsyncClient(
        timeout=20.0, follow_redirects=True, headers=DZZ_HTTP_HEADERS
    ) as client:
        response = await fetch_dzz_upstream(client, url, _auth_tuple(login, password))
    kind = classify_upstream(
        response.status_code,
        response.headers.get("content-type", ""),
        response.content or b"",
    )
    if kind == STATUS_BAD_CREDENTIALS:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Неверные учётные данные dzz.by")
    if kind == STATUS_UNAVAILABLE and dzz_source:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="dzz.by недоступен")
    if response.status_code != 200 or not response.content:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="Не удалось загрузить WMTSCapabilities")
    if len(response.content) > WMTS_MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="WMTSCapabilities слишком большой")
    return response.text


async def annotate_wmts_reachable(
    catalog: dict[str, Any], login: str, password: str, source: str
) -> dict[str, Any]:
    suggested = catalog.get("suggested")
    if not suggested:
        return catalog
    template = suggested.get("tileUrlTemplate") or ""
    if not template:
        return catalog
    probe = (
        template.replace("{TileMatrix}", "4")
        .replace("{TileRow}", "5")
        .replace("{TileCol}", "9")
        .replace("{z}", "4")
        .replace("{y}", "5")
        .replace("{x}", "9")
    )
    if not probe.startswith("http"):
        return catalog
    try:
        async with httpx.AsyncClient(
            timeout=8.0, follow_redirects=True, headers=DZZ_HTTP_HEADERS
        ) as client:
            response = await client.get(probe, auth=_auth_tuple(login, password))
            code = response.status_code
    except httpx.HTTPError:
        return catalog
    matrices = catalog.get("tileMatrixSets") or []
    for matrix in matrices:
        if matrix.get("id") == suggested.get("matrix"):
            matrix["reachable"] = code not in {520, 404, 500}
            matrix["status"] = code
            if source == "dzz" and matrix.get("wellKnown") == "GoogleMapsCompatible" and code == 520:
                matrix["reachable"] = False
    catalog["suggested"] = pick_suggested_wmts(
        catalog.get("layers") or [],
        matrices,
        catalog.get("tileUrlTemplate") or "",
    )
    return catalog


async def wmts_capabilities(
    request: Request,
    url: str | None,
    login: str = "",
    password: str = "",
) -> dict[str, Any]:
    row = _session_from_request(request)
    source = "custom"
    if url and _is_dzz_url(url) or (not url and row):
        source = "dzz"
        if row is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Нет сессии dzz.by")
        root = resolve_dzz_service_root(url or row["url"])
        caps_url = resolve_wmts_capabilities_url(root)
        _assert_dzz_origin(caps_url)
        login, password = row["login"], row["password"]
    else:
        if not url:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="URL WMTS не указан")
        caps_url = resolve_wmts_capabilities_url(url)
        parsed = urlparse(caps_url)
        if parsed.scheme not in {"http", "https"}:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Некорректный URL WMTS")
    xml_text = await _download_wmts_xml(caps_url, login, password)
    catalog = parse_wmts_capabilities(xml_text)
    catalog["source"] = source
    catalog["capabilitiesUrl"] = caps_url
    if source == "dzz":
        catalog = await annotate_wmts_reachable(catalog, login, password, source)
    return catalog


async def wmts_capabilities_flat(request: Request) -> list[dict[str, str]]:
    row = _session_from_request(request)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="dzz connection not found")
    catalog = await wmts_capabilities(request, row["url"])
    xml_layers = catalog.get("layers") or []
    items: list[dict[str, str]] = []
    for layer in xml_layers:
        matrix = (layer.get("tileMatrixSets") or [""])[0]
        style = layer.get("defaultStyle") or "default"
        items.append({"layer": layer["id"], "tilematrix": matrix, "style": style})
    return items


def _site_center_and_bounds(geometry: dict[str, Any]) -> tuple[list[float], list[float]] | None:
    rings = geometry.get("rings") or geometry.get("paths") or []
    xs: list[float] = []
    ys: list[float] = []
    for ring in rings:
        for point in ring:
            if len(point) < 2:
                continue
            xs.append(float(point[0]))
            ys.append(float(point[1]))
    if not xs:
        x = geometry.get("x")
        y = geometry.get("y")
        if x is None or y is None:
            return None
        return [float(y), float(x)], [float(x), float(y), float(x), float(y)]
    west, east = min(xs), max(xs)
    south, north = min(ys), max(ys)
    return [(south + north) / 2, (west + east) / 2], [west, south, east, north]


def parse_dzz_sites(payload: dict[str, Any]) -> list[dict[str, Any]]:
    features = payload.get("features") if isinstance(payload, dict) else None
    if not isinstance(features, list):
        return []
    sites: list[dict[str, Any]] = []
    for idx, feature in enumerate(features):
        if not isinstance(feature, dict):
            continue
        attrs = feature.get("attributes") or {}
        geom = feature.get("geometry") or {}
        parsed = _site_center_and_bounds(geom) if isinstance(geom, dict) else None
        if not parsed:
            continue
        center, bounds = parsed
        name = str(attrs.get("Name") or attrs.get("name") or attrs.get("TITLE") or f"Участок {idx + 1}")
        sites.append(
            {
                "id": attrs.get("OBJECTID") or attrs.get("FID") or idx,
                "name": name,
                "title": name,
                "center": center,
                "bounds": bounds,
            }
        )
    return sites


async def query_sites(request: Request) -> list[dict[str, Any]]:
    row = _session_from_request(request)
    if row is None:
        return []
    root = row["url"]
    query = "where=1%3D1&outFields=Name&returnGeometry=true&outSR=4326&f=json"
    path = urlparse(root).path.lstrip("/") + "/query"
    target = _proxy_target(root, path, query)
    auth = _auth_tuple(row["login"], row["password"])
    try:
        async with httpx.AsyncClient(
            timeout=20.0, follow_redirects=True, headers=DZZ_HTTP_HEADERS
        ) as client:
            response = await fetch_dzz_upstream(client, target, auth)
    except httpx.HTTPError:
        return []
    if response.status_code != 200 or not looks_like_json(
        response.headers.get("content-type", ""), response.content or b""
    ):
        return []
    try:
        payload = response.json()
    except ValueError:
        return []
    return parse_dzz_sites(payload)


async def regions(request: Request) -> list[list]:
    sites = await query_sites(request)
    return [[item["name"], item["center"][0], item["center"][1]] for item in sites]


_parse_wmts = parse_wmts_layers_flat
