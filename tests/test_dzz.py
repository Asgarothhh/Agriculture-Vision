import json

import httpx
import pytest

from app.dzz_service.service import (
    DZZ_DEFAULT_SERVICE,
    TRANSPARENT_PNG,
    classify_upstream,
    image_server_tile_url,
    looks_like_json,
    normalize_service_url,
    parse_dzz_sites,
    resolve_dzz_service_root,
    _parse_wmts,
    _tile_bbox_3857,
)
from app.dzz_service.wmts import parse_wmts_capabilities, resolve_wmts_capabilities_url

POLYA = "https://www.dzz.by/arcgis/rest/services/georesursDDZ/Polya_all/ImageServer"


class DummyClient:
    def __init__(self, handler):
        self.handler = handler

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def request(self, method, url, **kwargs):
        return self.handler(method, url, **kwargs)

    async def get(self, url, **kwargs):
        return await self.request("GET", url, **kwargs)


def test_classify_json_401_is_bad_credentials():
    body = b'{"error":{"code":499,"message":"Token Required"}}'
    assert looks_like_json("text/html", body)
    assert classify_upstream(401, "application/json", body) == "bad_credentials"
    assert classify_upstream(403, "application/json", body) == "bad_credentials"


def test_classify_html_401_is_unavailable():
    body = b"<html><h1>Access denied</h1></html>"
    assert not looks_like_json("text/html", body)
    assert classify_upstream(401, "text/html", body) == "unavailable"
    assert classify_upstream(403, "text/plain", b"forbidden") == "unavailable"


def test_default_service_is_polya_all():
    assert "Polya_all" in DZZ_DEFAULT_SERVICE
    assert resolve_dzz_service_root(POLYA) == POLYA
    assert resolve_dzz_service_root(
        POLYA + "/WMTS/1.0.0/WMTSCapabilities.xml"
    ) == POLYA


def test_foreign_host_is_rejected():
    with pytest.raises(Exception) as exc:
        resolve_dzz_service_root("https://evil.example/arcgis/rest/services/a/b/ImageServer")
    assert exc.value.status_code == 400


def test_image_server_tile_url_uses_zoom_offset_inside_cache_range():
    assert image_server_tile_url(POLYA, 12, 2400, 1309) == f"{POLYA}/tile/4/1309/2400"
    assert image_server_tile_url(POLYA, 10, 1, 2) == f"{POLYA}/tile/2/2/1"
    assert "exportImage" in image_server_tile_url(POLYA, 8, 140, 85)
    assert "exportImage" in image_server_tile_url(POLYA, 16, 1, 1)


def test_normalize_strips_tile_template():
    raw = POLYA + "/tile/{z}/{y}/{x}"
    assert normalize_service_url(raw) == POLYA


def test_tile_bbox_is_web_mercator():
    minx, miny, maxx, maxy = _tile_bbox_3857(0, 0, 0)
    assert minx < 0 < maxx
    assert miny < 0 < maxy


def test_transparent_png_signature():
    assert TRANSPARENT_PNG.startswith(b"\x89PNG")


def test_parse_wmts_layers():
    xml = """<?xml version="1.0"?>
    <Capabilities xmlns="http://www.opengis.net/wmts/1.0" xmlns:ows="http://www.opengis.net/ows/1.1">
      <Contents>
        <Layer>
          <ows:Identifier>ortho</ows:Identifier>
          <TileMatrixSetLink><TileMatrixSet>EPSG:3857</TileMatrixSet></TileMatrixSetLink>
          <Style isDefault="true"><ows:Identifier>default</ows:Identifier></Style>
          <ResourceURL resourceType="tile" template="https://www.dzz.by/arcgis/rest/services/x/y/ImageServer/WMTS/tile/1.0.0/{Style}/{TileMatrixSet}/{TileMatrix}/{TileRow}/{TileCol}"/>
        </Layer>
        <TileMatrixSet>
          <ows:Identifier>EPSG:3857</ows:Identifier>
          <ows:SupportedCRS>urn:ogc:def:crs:EPSG:6.18.3:3857</ows:SupportedCRS>
        </TileMatrixSet>
        <TileMatrixSet>
          <ows:Identifier>GoogleMapsCompatible</ows:Identifier>
          <ows:SupportedCRS>urn:ogc:def:crs:EPSG:6.18.3:3857</ows:SupportedCRS>
        </TileMatrixSet>
      </Contents>
    </Capabilities>
    """
    items = _parse_wmts(xml)
    assert items
    assert items[0]["layer"] == "ortho"
    catalog = parse_wmts_capabilities(xml)
    assert catalog["suggested"]["layer"] == "ortho"
    assert catalog["suggested"]["matrix"] == "EPSG:3857"
    assert "TileMatrix" in catalog["tileUrlTemplate"]


def test_resolve_wmts_capabilities_url():
    assert resolve_wmts_capabilities_url(POLYA).endswith("/WMTS/1.0.0/WMTSCapabilities.xml")


def test_parse_dzz_sites():
    payload = {
        "features": [
            {
                "attributes": {"Name": "Поле 1", "OBJECTID": 7},
                "geometry": {"rings": [[[27.4, 53.8], [27.5, 53.8], [27.5, 53.9], [27.4, 53.9], [27.4, 53.8]]]},
            }
        ]
    }
    sites = parse_dzz_sites(payload)
    assert sites[0]["name"] == "Поле 1"
    assert sites[0]["center"][0] == pytest.approx(53.85)
    assert sites[0]["bounds"][0] == pytest.approx(27.4)


def test_openapi_dzz_routes(client):
    paths = client.get("/api/v1/openapi.json").json()["paths"]
    assert "/api/v1/dzz/connect" in paths
    assert "/api/v1/dzz/check" in paths
    assert "/api/v1/dzz/health" in paths
    assert "/api/v1/dzz/tiles/{z}/{x}/{y}" in paths
    assert "/api/v1/dzz/wmts/capabilities" in paths
    assert "/api/v1/wmts/capabilities" in paths
    assert "/api/v1/dzz/regions" in paths
    assert "/api/v1/dzz/sites" in paths


def test_health_endpoint(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_status_without_cookie_is_disconnected(client):
    response = client.get("/api/v1/dzz/status")
    assert response.status_code == 200
    assert response.json()["connected"] is False


def test_proxy_without_session_is_unauthorized(client):
    response = client.get("/api/v1/dzz/arcgis/rest/services/georesursDDZ/Polya_all/ImageServer/tile/4/1/1")
    assert response.status_code == 401


def test_proxy_rejects_non_arcgis_path(client, monkeypatch):
    async def fake_probe(login, password, root):
        return "online"

    monkeypatch.setattr("app.dzz_service.service.probe_dzz_service", fake_probe)
    connected = client.post(
        "/api/v1/dzz/connect",
        json={"login": "u", "password": "p", "url": POLYA},
    )
    assert connected.status_code == 200, connected.text
    assert client.cookies.get("dzz_sid")
    blocked = client.get("/api/v1/dzz/not-arcgis/secret")
    assert blocked.status_code == 403


def test_connect_sets_cookie_and_disconnect_clears_it(client, monkeypatch):
    async def fake_probe(login, password, root):
        return "online"

    monkeypatch.setattr("app.dzz_service.service.probe_dzz_service", fake_probe)
    connected = client.post(
        "/api/v1/dzz/connect",
        json={"login": "u", "password": "p", "url": POLYA},
    )
    assert connected.status_code == 200
    assert connected.json()["service_url"] == POLYA
    assert client.cookies.get("dzz_sid")
    status = client.get("/api/v1/dzz/status")
    assert status.json()["connected"] is True
    tiles = client.get("/api/v1/dzz/tiles/1/1/1")
    assert tiles.status_code == 200
    gone = client.post("/api/v1/dzz/disconnect")
    assert gone.status_code == 200
    assert client.get("/api/v1/dzz/status").json()["connected"] is False


def test_connect_html_401_is_unavailable(client, monkeypatch):
    def handler(_method, _url, **_kwargs):
        return httpx.Response(401, headers={"content-type": "text/html"}, content=b"<html>denied</html>")

    monkeypatch.setattr(
        "app.dzz_service.service.httpx.AsyncClient",
        lambda *args, **kwargs: DummyClient(handler),
    )
    response = client.post(
        "/api/v1/dzz/connect",
        json={"login": "u", "password": "p", "url": POLYA},
    )
    assert response.status_code == 503


def test_connect_json_401_is_bad_credentials(client, monkeypatch):
    def handler(_method, _url, **_kwargs):
        return httpx.Response(
            401,
            headers={"content-type": "application/json"},
            content=json.dumps({"error": {"code": 499, "message": "Token Required"}}).encode(),
        )

    monkeypatch.setattr(
        "app.dzz_service.service.httpx.AsyncClient",
        lambda *args, **kwargs: DummyClient(handler),
    )
    response = client.post(
        "/api/v1/dzz/connect",
        json={"login": "u", "password": "p", "url": POLYA},
    )
    assert response.status_code == 401
    assert "учётные данные" in response.json()["detail"]
