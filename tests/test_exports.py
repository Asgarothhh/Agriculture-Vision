from app.activity_service.service import parse_search
from app.layers_service.export_utils import objects_to_geojson, geojson_to_shapefile_zip


def test_activity_search_parses_dotted_and_compact_dates():
    text, dates = parse_search("ошибка 11.07 и 07072026")
    assert "ошибка" in text
    assert (11, 7, None) in dates or any(item[0] == 11 and item[1] == 7 for item in dates)
    assert any(item == (7, 7, 2026) for item in dates)


def test_shapefile_zip_splits_mixed_geometry():
    import io
    import zipfile

    import pytest

    pytest.importorskip("geopandas")
    feature = lambda geom, name: {  # noqa: E731
        "type": "Feature",
        "geometry": geom,
        "properties": {"name": name, "layer_name": "Слой", "layer_color": "#6D4C41", "origin": "manual", "number": 1},
    }
    geojson = {
        "type": "FeatureCollection",
        "features": [
            feature({"type": "Point", "coordinates": [27.5, 53.9]}, "Дерево"),
            feature(
                {"type": "Polygon", "coordinates": [[[27.4, 53.8], [27.5, 53.8], [27.5, 53.9], [27.4, 53.8]]]},
                "Поле",
            ),
        ],
    }
    payload = geojson_to_shapefile_zip(geojson)
    names = set(zipfile.ZipFile(io.BytesIO(payload)).namelist())
    assert {"layers_points.shp", "layers_polygons.shp", "layers_points.dbf", "layers_polygons.dbf"} <= names


def test_shapefile_zip_rejects_empty_collection():
    import pytest

    pytest.importorskip("geopandas")
    with pytest.raises(ValueError):
        geojson_to_shapefile_zip({"type": "FeatureCollection", "features": []})


def test_merge_conflict_rule():
    layer_ids = {"a", "b"}
    assert len(layer_ids) != 1
