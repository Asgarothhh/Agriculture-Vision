from __future__ import annotations

import io
import json
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Iterable
from uuid import UUID

from shapely.geometry import mapping, shape


def objects_to_geojson(layers: Iterable[dict[str, Any]]) -> dict[str, Any]:
    features = []
    for layer in layers:
        for obj in layer["objects"]:
            features.append(
                {
                    "type": "Feature",
                    "id": str(obj["id"]),
                    "geometry": obj["geom"],
                    "properties": {
                        "layer_id": str(layer["id"]),
                        "layer_name": layer["name"],
                        "layer_color": layer["color"],
                        "folder": layer.get("folder_name"),
                        "name": obj["name"],
                        "number": obj["number"],
                        "is_point": obj["is_point"],
                        "origin": obj["origin"],
                        "area_ha": obj.get("area_ha"),
                    },
                }
            )
    return {"type": "FeatureCollection", "features": features}


def geojson_to_kml(geojson: dict[str, Any]) -> bytes:
    import simplekml

    kml = simplekml.Kml()
    for feature in geojson.get("features", []):
        props = feature.get("properties") or {}
        name = props.get("name") or props.get("layer_name") or "object"
        geom = feature.get("geometry") or {}
        gtype = geom.get("type")
        coords = geom.get("coordinates")
        if gtype == "Point":
            pnt = kml.newpoint(name=name, coords=[tuple(coords)])
            pnt.style.iconstyle.color = _kml_color(props.get("layer_color"))
        elif gtype == "Polygon":
            pol = kml.newpolygon(name=name, outerboundaryis=[tuple(c) for c in coords[0]])
            pol.style.polystyle.color = _kml_color(props.get("layer_color"), opacity="7f")
        elif gtype == "MultiPolygon":
            for poly in coords:
                pol = kml.newpolygon(name=name, outerboundaryis=[tuple(c) for c in poly[0]])
                pol.style.polystyle.color = _kml_color(props.get("layer_color"), opacity="7f")
        elif gtype == "LineString":
            kml.newlinestring(name=name, coords=[tuple(c) for c in coords])
    return kml.kml().encode("utf-8")


def _kml_color(hex_color: str | None, opacity: str = "ff") -> str:
    raw = (hex_color or "#2E7D32").lstrip("#")
    if len(raw) != 6:
        raw = "2E7D32"
    r, g, b = raw[0:2], raw[2:4], raw[4:6]
    return f"{opacity}{b}{g}{r}"


def geojson_to_shapefile_zip(geojson: dict[str, Any]) -> bytes:
    import geopandas as gpd

    rows = []
    for feature in geojson.get("features", []):
        geom = shape(feature["geometry"]) if feature.get("geometry") else None
        props = feature.get("properties") or {}
        rows.append(
            {
                "name": str(props.get("name") or "")[:50],
                "layer": str(props.get("layer_name") or "")[:50],
                "color": str(props.get("layer_color") or "")[:16],
                "origin": str(props.get("origin") or "")[:16],
                "is_point": bool(props.get("is_point")),
                "number": int(props.get("number") or 0),
                "geometry": geom,
            }
        )
    if not rows:
        gdf = gpd.GeoDataFrame(columns=["name", "geometry"], geometry="geometry", crs="EPSG:4326")
    else:
        gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
    with tempfile.TemporaryDirectory() as tmp:
        shp_path = Path(tmp) / "export.shp"
        gdf.to_file(shp_path, driver="ESRI Shapefile")
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for file in Path(tmp).iterdir():
                zf.write(file, arcname=file.name)
        return buffer.getvalue()


def geojson_to_svg(geojson: dict[str, Any], size: int = 1024) -> bytes:
    xs: list[float] = []
    ys: list[float] = []
    features = geojson.get("features") or []
    for feature in features:
        geom = feature.get("geometry") or {}
        _collect_coords(geom.get("coordinates"), xs, ys)
    if not xs:
        return b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"></svg>'
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    dx = max(max_x - min_x, 1e-9)
    dy = max(max_y - min_y, 1e-9)
    pad = 20
    inner = size - 2 * pad

    def tx(x: float, y: float) -> tuple[float, float]:
        return pad + (x - min_x) / dx * inner, pad + (max_y - y) / dy * inner

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}">'
    ]
    for feature in features:
        color = (feature.get("properties") or {}).get("layer_color") or "#2E7D32"
        geom = feature.get("geometry") or {}
        gtype = geom.get("type")
        coords = geom.get("coordinates")
        if gtype == "Point":
            x, y = tx(coords[0], coords[1])
            parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4" fill="{color}"/>')
        elif gtype == "Polygon":
            parts.append(_svg_polygon(coords[0], tx, color))
        elif gtype == "MultiPolygon":
            for poly in coords:
                parts.append(_svg_polygon(poly[0], tx, color))
        elif gtype == "LineString":
            pts = " ".join(f"{tx(c[0], c[1])[0]:.2f},{tx(c[0], c[1])[1]:.2f}" for c in coords)
            parts.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2"/>')
    parts.append("</svg>")
    return "".join(parts).encode("utf-8")


def _svg_polygon(ring: list, tx, color: str) -> str:
    pts = " ".join(f"{tx(c[0], c[1])[0]:.2f},{tx(c[0], c[1])[1]:.2f}" for c in ring)
    return f'<polygon points="{pts}" fill="{color}" fill-opacity="0.35" stroke="{color}" stroke-width="1"/>'


def _collect_coords(coords: Any, xs: list[float], ys: list[float]) -> None:
    if not coords:
        return
    if isinstance(coords[0], (int, float)):
        xs.append(float(coords[0]))
        ys.append(float(coords[1]))
        return
    for item in coords:
        _collect_coords(item, xs, ys)
