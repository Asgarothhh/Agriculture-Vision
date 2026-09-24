from app.layers_service.export_utils import objects_to_geojson, geojson_to_kml, geojson_to_svg
from app.layers_service.schemas import MergeRequest
from pydantic import ValidationError
import pytest


def test_merge_requires_two_ids():
    with pytest.raises(ValidationError):
        MergeRequest(object_ids=["00000000-0000-0000-0000-000000000001"])


def test_geojson_export_contains_layer_metadata():
    layers = [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "name": "Поля",
            "color": "#43A047",
            "folder_name": "Сезон 2026",
            "objects": [
                {
                    "id": "22222222-2222-2222-2222-222222222222",
                    "name": "Участок 1",
                    "number": 1,
                    "geom": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
                    "is_point": False,
                    "origin": "auto",
                    "area_ha": 1.2,
                }
            ],
        }
    ]
    geojson = objects_to_geojson(layers)
    props = geojson["features"][0]["properties"]
    assert props["layer_name"] == "Поля"
    assert props["layer_color"] == "#43A047"
    assert props["folder"] == "Сезон 2026"
    assert props["origin"] == "auto"
    assert props["is_point"] is False


def test_kml_and_svg_export_not_empty():
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[27.0, 53.0], [27.1, 53.0], [27.1, 53.1], [27.0, 53.0]]]},
                "properties": {"name": "Поле", "layer_color": "#2E7D32"},
            }
        ],
    }
    kml = geojson_to_kml(geojson)
    svg = geojson_to_svg(geojson)
    assert b"<kml" in kml or b"<Polygon>" in kml
    assert b"<svg" in svg


def test_openapi_layer_routes(client):
    paths = client.get("/api/v1/openapi.json").json()["paths"]
    assert "/api/v1/layers/" in paths
    assert "/api/v1/layers/import" in paths
    assert "/api/v1/layers/export" in paths
    assert "/api/v1/objects/merge" in paths
    assert "/api/v1/folders/" in paths
    assert "/api/v1/layers/{layer_id}/objects" in paths
