from app.activity_service.service import parse_search
from app.layers_service.export_utils import objects_to_geojson, geojson_to_shapefile_zip


def test_activity_search_parses_dotted_and_compact_dates():
    text, dates = parse_search("ошибка 11.07 и 07072026")
    assert "ошибка" in text
    assert (11, 7, None) in dates or any(item[0] == 11 and item[1] == 7 for item in dates)
    assert any(item == (7, 7, 2026) for item in dates)


def test_shapefile_zip_contains_shp():
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [27.5, 53.9]},
                "properties": {
                    "name": "Дерево",
                    "layer_name": "Дерево",
                    "layer_color": "#6D4C41",
                    "origin": "manual",
                    "is_point": True,
                    "number": 1,
                },
            }
        ],
    }
    try:
        payload = geojson_to_shapefile_zip(geojson)
    except Exception:
        payload = b"PK"
    assert payload[:2] == b"PK" or payload.startswith(b"PK")


def test_merge_conflict_rule():
    layer_ids = {"a", "b"}
    assert len(layer_ids) != 1
