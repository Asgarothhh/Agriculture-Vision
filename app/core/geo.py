from __future__ import annotations

from typing import Any

from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def geojson_to_shape(geom: dict[str, Any]) -> BaseGeometry:
    return shape(geom)


def shape_to_geojson(geom: Any) -> dict[str, Any]:
    if hasattr(geom, "desc"):
        geom = to_shape(geom)
    return mapping(geom)


def wkb_element(geom: dict[str, Any] | BaseGeometry, srid: int = 4326):
    if isinstance(geom, dict):
        geom = geojson_to_shape(geom)
    return from_shape(geom, srid=srid)


async def st_area_m2(db: AsyncSession, geom_wkt: str, srid: int = 4326) -> float:
    result = await db.execute(
        text(
            "SELECT ST_Area(ST_Transform(ST_GeomFromText(:wkt, :srid), 4326)::geography)"
        ),
        {"wkt": geom_wkt, "srid": srid},
    )
    value = result.scalar()
    return float(value or 0.0)


def format_area(area_m2: float) -> dict[str, float | str]:
    if area_m2 < 100:
        return {"area": round(area_m2, 2), "unit": "m2", "area_ha": area_m2 / 10_000}
    return {"area": round(area_m2 / 10_000, 4), "unit": "ha", "area_ha": area_m2 / 10_000}
