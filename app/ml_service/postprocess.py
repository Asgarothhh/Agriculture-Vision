from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from geoalchemy2.functions import ST_AsGeoJSON, ST_Transform
from shapely.geometry import mapping, shape
from shapely.ops import transform as shapely_transform
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.geo import wkb_element
from app.ml_service.models import CropProbability, ModelRegistry, PointObject, PolygonObject
from app.ml_service.schemas import InferenceFeature, InferenceResponse
from app.tasks_service.models import Image, ProcessingTask


def _srid_from_crs(crs: str) -> int:
    if not crs:
        return 4326
    if ":" in crs:
        try:
            return int(crs.split(":")[-1])
        except ValueError:
            return 4326
    try:
        return int(crs)
    except ValueError:
        return 4326


def _affine_pixel_to_geo(coords: Any, transform: list[float] | None) -> Any:
    if not transform or len(transform) < 6:
        return coords
    a, b, c, d, e, f = transform[:6]

    def apply(x: float, y: float) -> tuple[float, float]:
        # rasterio affine: x_geo = a + x * pixel_width..., typically [c, a, b, f, d, e] GDAL order
        # We store GDAL geotransform: [c, a, b, f, d, e] as six floats from rasterio.transform.to_gdal()
        return c + x * a + y * b, f + x * d + y * e

    if isinstance(coords[0], (int, float)):
        return list(apply(float(coords[0]), float(coords[1])))
    return [_affine_pixel_to_geo(item, transform) for item in coords]


def georeference_geometry(
    geometry: dict[str, Any],
    transform: list[float] | None,
    pixel_space: bool,
) -> dict[str, Any]:
    if not pixel_space or not transform or len(transform) < 6:
        return geometry
    geom = shape(geometry)
    c, a, b, f, d, e = transform[:6]

    def _proj(x, y, z=None):
        return (c + x * a + y * b, f + x * d + y * e)

    return mapping(shapely_transform(_proj, geom))


def persist_inference(
    session: Session,
    image: Image,
    response: InferenceResponse,
    threshold: float,
    transform: list[float] | None = None,
    pixel_space: bool = False,
) -> None:
    model = session.scalar(select(ModelRegistry).where(ModelRegistry.code == response.model))
    if model is None:
        model = session.scalar(select(ModelRegistry).limit(1))
    if model is None:
        raise RuntimeError("models_registry is empty")
    srid = _srid_from_crs(image.crs)

    for feat in response.polygons:
        geom = georeference_geometry(feat.geometry, transform, pixel_space)
        poly = PolygonObject(
            image_id=image.id,
            model_id=model.id,
            class_id=feat.class_id,
            geom=wkb_element(geom, srid),
            confidence=feat.confidence,
            needs_manual_check=feat.confidence < threshold,
        )
        session.add(poly)
        session.flush()
        if feat.crop_probabilities:
            for crop_id, prob in feat.crop_probabilities.items():
                session.add(
                    CropProbability(
                        polygon_id=poly.id,
                        crop_class_id=int(crop_id),
                        probability=float(prob),
                    )
                )

    for feat in response.points:
        geom = georeference_geometry(feat.geometry, transform, pixel_space)
        session.add(
            PointObject(
                image_id=image.id,
                model_id=model.id,
                class_id=feat.class_id,
                geom=wkb_element(geom, srid),
                radius_approx=feat.radius_approx,
                area_approx=feat.area_approx,
                confidence=feat.confidence,
            )
        )


async def results_to_geojson(db: AsyncSession, task: ProcessingTask) -> dict[str, Any]:
    if task.image is None:
        return {"type": "FeatureCollection", "features": []}
    image_id = task.image.id
    features: list[dict[str, Any]] = []

    polygons = (
        await db.execute(select(PolygonObject).where(PolygonObject.image_id == image_id))
    ).scalars().all()
    for poly in polygons:
        geo = await db.scalar(select(ST_AsGeoJSON(ST_Transform(poly.geom, 4326))))
        features.append(
            {
                "type": "Feature",
                "id": str(poly.id),
                "geometry": json.loads(geo) if geo else None,
                "properties": {
                    "kind": "polygon",
                    "class_id": poly.class_id,
                    "confidence": poly.confidence,
                    "needs_manual_check": poly.needs_manual_check,
                    "origin": "auto",
                },
            }
        )

    points = (
        await db.execute(select(PointObject).where(PointObject.image_id == image_id))
    ).scalars().all()
    for point in points:
        geo = await db.scalar(select(ST_AsGeoJSON(ST_Transform(point.geom, 4326))))
        features.append(
            {
                "type": "Feature",
                "id": str(point.id),
                "geometry": json.loads(geo) if geo else None,
                "properties": {
                    "kind": "point",
                    "class_id": point.class_id,
                    "confidence": point.confidence,
                    "radius_approx": point.radius_approx,
                    "area_approx": point.area_approx,
                    "origin": "auto",
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}
