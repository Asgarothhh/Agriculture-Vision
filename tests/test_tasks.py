import pytest

from app.core.geo import format_area
from app.ml_service.postprocess import georeference_geometry


def test_format_area_uses_square_meters_for_small_plots():
    result = format_area(42.0)
    assert result["unit"] == "m2"
    assert result["area"] == 42.0


def test_format_area_uses_hectares_for_large_plots():
    result = format_area(25_000)
    assert result["unit"] == "ha"
    assert result["area"] == 2.5


def test_georeference_pixel_point():
    geometry = {"type": "Point", "coordinates": [10, 20]}
    transform = [100.0, 2.0, 0.0, 200.0, 0.0, -2.0]
    geo = georeference_geometry(geometry, transform, pixel_space=True)
    assert geo["coordinates"][0] == pytest.approx(120)
    assert geo["coordinates"][1] == pytest.approx(160)


def test_georeference_identity_without_transform():
    geometry = {"type": "Point", "coordinates": [27.5, 53.9]}
    assert georeference_geometry(geometry, None, True) == geometry


def test_openapi_task_and_model_routes(client):
    paths = client.get("/api/v1/openapi.json").json()["paths"]
    assert "/api/v1/tasks/" in paths
    assert "/api/v1/tasks/{task_id}/result" in paths
    assert "/api/v1/tasks/{task_id}/to-layers" in paths
    assert "/api/v1/models/" in paths
    assert "/api/v1/models/health" in paths
    assert "/api/v1/classes/" in paths
