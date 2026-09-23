from app.dzz_service.service import TRANSPARENT_PNG, _parse_wmts, _tile_urls


def test_tile_url_templates_include_both_orders():
    urls = _tile_urls("https://dzz.by/tiles", 8, 140, 85)
    assert any("/8/140/85" in url for url in urls)
    assert any("/8/85/140" in url for url in urls)


def test_image_server_tile_urls_prefer_arcgis_order():
    root = "https://www.dzz.by/arcgis/rest/services/georesursDDZ/Polya_all/ImageServer"
    urls = _tile_urls(root, 12, 2360, 1180)
    assert f"{root}/tile/12/1180/2360" in urls
    assert f"{root}/tile/12/2360/1180" in urls
    assert urls[0].endswith("/tile/12/1180/2360")


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
