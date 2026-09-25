from app.dzz_service.service import (
    TRANSPARENT_PNG,
    _google_lod,
    _looks_like_image,
    _parse_wmts,
    _tile_bbox_3857,
    _tile_urls,
    effective_service_url,
    normalize_service_url,
)


def test_tile_url_templates_include_both_orders():
    urls = _tile_urls("https://dzz.by/tiles", 8, 140, 85)
    assert any("/8/140/85" in url for url in urls)
    assert any("/8/85/140" in url for url in urls)


def test_image_server_tile_urls_prefer_arcgis_order():
    root = "https://www.dzz.by/arcgis/rest/services/georesursDDZ/Belarus_web_mercator_all/ImageServer"
    urls = _tile_urls(root, 12, 2360, 1180)
    assert f"{root}/tile/12/1180/2360" in urls
    assert f"{root}/tile/12/2360/1180" in urls
    assert urls[0].endswith("/tile/12/1180/2360")
    assert any("exportImage" in url and "format=jpg" in url for url in urls)


def test_polya_all_remaps_to_nationwide_ortho():
    raw = "https://www.dzz.by/arcgis/rest/services/georesursDDZ/Polya_all/ImageServer"
    assert (
        effective_service_url(raw)
        == "https://www.dzz.by/arcgis/rest/services/georesursDDZ/Belarus_web_mercator_all/ImageServer"
    )
    urls = _tile_urls(raw, 12, 2361, 1316)
    assert all("Polya_all" not in url for url in urls)
    assert any("Belarus_web_mercator_all" in url for url in urls)


def test_google_lod_matches_standard_web_mercator():
    lods = [{"level": i, "resolution": 156543.03392804097 / (2**i)} for i in range(21)]
    assert _google_lod(lods, 12) == 12
    offset_lods = [{"level": i, "resolution": 156543.03392804097 / (2 ** (i + 8))} for i in range(15)]
    assert _google_lod(offset_lods, 12) == 4


def test_normalize_strips_tile_template():
    raw = "https://www.dzz.by/arcgis/rest/services/georesursDDZ/Polya_all/ImageServer/tile/{z}/{y}/{x}"
    assert (
        normalize_service_url(raw)
        == "https://www.dzz.by/arcgis/rest/services/georesursDDZ/Polya_all/ImageServer"
    )


def test_looks_like_image_rejects_json_and_placeholder():
    assert not _looks_like_image(TRANSPARENT_PNG, "image/png")
    assert not _looks_like_image(b'{"error":1}', "application/json")
    fake_png = TRANSPARENT_PNG.replace(b"IHDR", b"IHDR")  # still 1x1
    assert not _looks_like_image(fake_png, "image/png")
    bigger = b"\x89PNG\r\n\x1a\n" + b"x" * 1600
    assert _looks_like_image(bigger, "image/png")
    assert not _looks_like_image(b"\xff\xd8" + b"\x00" * 200, "image/jpeg")


def test_transparent_png_is_not_cacheable():
    """Fallback 1×1 PNG must never be treated as a cacheable ortho tile."""
    assert not _looks_like_image(TRANSPARENT_PNG, "image/png")


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
          <Style><ows:Identifier>default</ows:Identifier></Style>
        </Layer>
      </Contents>
    </Capabilities>
    """
    items = _parse_wmts(xml)
    assert items
    assert items[0]["layer"] == "ortho"


def test_openapi_dzz_routes(client):
    paths = client.get("/api/v1/openapi.json").json()["paths"]
    assert "/api/v1/dzz/connect" in paths
    assert "/api/v1/dzz/check" in paths
    assert "/api/v1/dzz/tiles/{z}/{x}/{y}" in paths
    assert "/api/v1/dzz/wmts/capabilities" in paths
    assert "/api/v1/dzz/regions" in paths


def test_health_endpoint(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
