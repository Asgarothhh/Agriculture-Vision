from __future__ import annotations

import io
import json
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import HTTPException, UploadFile, status
from geoalchemy2.functions import ST_AsGeoJSON, ST_Area, ST_Transform, ST_Union
from geoalchemy2.shape import to_shape
from shapely.geometry import mapping, shape
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.activity_service.service import log_event
from app.core.geo import format_area, geojson_to_shape, shape_to_geojson, wkb_element
from app.layers_service.export_utils import (
    geojson_to_kml,
    geojson_to_shapefile_zip,
    geojson_to_svg,
    objects_to_geojson,
)
from app.layers_service.models import Folder, Layer, LayerObject
from app.layers_service.schemas import (
    ExportRequest,
    FolderCreate,
    FolderItems,
    FolderUpdate,
    LayerCreate,
    LayerUpdate,
    MergeRequest,
    ObjectCreate,
    ObjectUpdate,
)
from app.users_service.models import User


async def list_layers(db: AsyncSession, user: User, search: str | None = None) -> list[dict[str, Any]]:
    stmt = (
        select(Layer, func.count(LayerObject.id))
        .outerjoin(Layer.objects)
        .where(Layer.user_id == user.id)
        .group_by(Layer.id)
        .order_by(Layer.created_at.asc())
    )
    if search:
        stmt = stmt.where(Layer.name.ilike(f"%{search}%"))
    rows = (await db.execute(stmt)).all()
    result = []
    for layer, count in rows:
        result.append(_layer_dict(layer, int(count)))
    return result


def _layer_dict(layer: Layer, objects_count: int | None = None) -> dict[str, Any]:
    return {
        "id": layer.id,
        "name": layer.name,
        "color": layer.color,
        "kind": layer.kind,
        "folder_id": layer.folder_id,
        "is_visible": layer.is_visible,
        "source_filename": layer.source_filename,
        "class_id": layer.class_id,
        "objects_count": objects_count if objects_count is not None else 0,
        "created_at": layer.created_at,
    }


async def create_layer(db: AsyncSession, user: User, data: LayerCreate) -> dict[str, Any]:
    layer = Layer(user_id=user.id, name=data.name, color=data.color, kind="user")
    db.add(layer)
    await db.commit()
    await db.refresh(layer)
    return _layer_dict(layer, 0)


async def get_owned_layer(db: AsyncSession, user: User, layer_id: UUID) -> Layer:
    layer = (
        await db.execute(select(Layer).where(Layer.id == layer_id, Layer.user_id == user.id))
    ).scalar_one_or_none()
    if layer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Layer not found")
    return layer


async def update_layer(db: AsyncSession, user: User, layer_id: UUID, data: LayerUpdate) -> dict[str, Any]:
    layer = await get_owned_layer(db, user, layer_id)
    if layer.kind == "auto" and data.name is not None and data.name != layer.name:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Системный слой нельзя переименовать")
    if data.name is not None:
        layer.name = data.name
    if data.color is not None:
        layer.color = data.color
    if data.is_visible is not None:
        layer.is_visible = data.is_visible
    if data.folder_id is not None:
        layer.folder_id = data.folder_id
    await db.commit()
    await db.refresh(layer)
    count = (
        await db.execute(select(func.count()).select_from(LayerObject).where(LayerObject.layer_id == layer.id))
    ).scalar_one()
    return _layer_dict(layer, int(count))


async def delete_layer(db: AsyncSession, user: User, layer_id: UUID) -> None:
    layer = await get_owned_layer(db, user, layer_id)
    if layer.kind == "auto":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Системный слой нельзя удалить")
    await db.delete(layer)
    await log_event(db, user.id, "map_tools", f"Удалён слой {layer.name}")
    await db.commit()


async def create_folder(db: AsyncSession, user: User, data: FolderCreate) -> Folder:
    folder = Folder(user_id=user.id, name=data.name)
    db.add(folder)
    await db.commit()
    await db.refresh(folder)
    return folder


async def get_owned_folder(db: AsyncSession, user: User, folder_id: UUID) -> Folder:
    folder = (
        await db.execute(select(Folder).where(Folder.id == folder_id, Folder.user_id == user.id))
    ).scalar_one_or_none()
    if folder is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Folder not found")
    return folder


async def update_folder(db: AsyncSession, user: User, folder_id: UUID, data: FolderUpdate) -> Folder:
    folder = await get_owned_folder(db, user, folder_id)
    if data.name is not None:
        folder.name = data.name
    if data.is_visible is not None:
        folder.is_visible = data.is_visible
    await db.commit()
    await db.refresh(folder)
    return folder


async def delete_folder(db: AsyncSession, user: User, folder_id: UUID) -> None:
    folder = await get_owned_folder(db, user, folder_id)
    await db.execute(update(Layer).where(Layer.folder_id == folder.id).values(folder_id=None))
    await db.execute(update(LayerObject).where(LayerObject.folder_id == folder.id).values(folder_id=None))
    await db.delete(folder)
    await db.commit()


async def move_folder_item(db: AsyncSession, user: User, folder_id: UUID, data: FolderItems) -> dict[str, Any]:
    if data.layer_id is None and data.object_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Specify layer_id or object_id")
    target = None if data.detach else folder_id
    if not data.detach:
        await get_owned_folder(db, user, folder_id)
    if data.layer_id:
        layer = await get_owned_layer(db, user, data.layer_id)
        layer.folder_id = target
    if data.object_id:
        obj = await get_owned_object(db, user, data.object_id)
        obj.folder_id = target
    await db.commit()
    return {"detail": "ok"}


async def list_layer_objects(db: AsyncSession, user: User, layer_id: UUID) -> list[dict[str, Any]]:
    layer = await get_owned_layer(db, user, layer_id)
    rows = (
        await db.execute(
            select(LayerObject)
            .where(LayerObject.layer_id == layer.id)
            .order_by(LayerObject.number.asc(), LayerObject.created_at.asc())
        )
    ).scalars().all()
    return [await object_payload(db, obj) for obj in rows]


async def add_object(db: AsyncSession, user: User, layer_id: UUID, data: ObjectCreate) -> dict[str, Any]:
    layer = await get_owned_layer(db, user, layer_id)
    shapely_geom = geojson_to_shape(data.geom)
    is_point = shapely_geom.geom_type == "Point"
    number = (
        await db.execute(
            select(func.coalesce(func.max(LayerObject.number), 0)).where(LayerObject.layer_id == layer.id)
        )
    ).scalar_one()
    obj = LayerObject(
        layer_id=layer.id,
        name=data.name or f"{layer.name} {int(number) + 1}",
        number=int(number) + 1,
        geom=wkb_element(shapely_geom, 4326),
        is_point=is_point,
        origin=data.origin,
        area_ha=None if is_point else shapely_geom.area,
    )
    db.add(obj)
    await db.flush()
    await recalc_area(db, obj)
    await log_event(db, user.id, "map_tools", f"Добавлен объект {obj.name}", {"object_id": str(obj.id)})
    await db.commit()
    await db.refresh(obj)
    return await object_payload(db, obj)


async def get_owned_object(db: AsyncSession, user: User, object_id: UUID) -> LayerObject:
    obj = (
        await db.execute(
            select(LayerObject)
            .join(Layer)
            .options(selectinload(LayerObject.layer))
            .where(LayerObject.id == object_id, Layer.user_id == user.id)
        )
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Object not found")
    return obj


async def object_payload(db: AsyncSession, obj: LayerObject) -> dict[str, Any]:
    geojson = json.loads(
        (await db.scalar(select(ST_AsGeoJSON(obj.geom)))) or "{}"
    )
    area_m2 = 0.0 if obj.is_point else float(obj.area_ha or 0) * 10_000
    formatted = format_area(area_m2)
    return {
        "id": obj.id,
        "layer_id": obj.layer_id,
        "name": obj.name,
        "number": obj.number,
        "geom": geojson,
        "is_point": obj.is_point,
        "origin": obj.origin,
        "area_ha": obj.area_ha,
        "area": formatted["area"],
        "unit": formatted["unit"],
        "created_at": obj.created_at,
        "updated_at": obj.updated_at,
    }


async def update_object(db: AsyncSession, user: User, object_id: UUID, data: ObjectUpdate) -> dict[str, Any]:
    obj = await get_owned_object(db, user, object_id)
    if data.name is not None:
        obj.name = data.name
    if data.geom is not None:
        shapely_geom = geojson_to_shape(data.geom)
        obj.geom = wkb_element(shapely_geom, 4326)
        obj.is_point = shapely_geom.geom_type == "Point"
    if data.layer_id is not None:
        layer = await get_owned_layer(db, user, data.layer_id)
        obj.layer_id = layer.id
    await db.flush()
    await recalc_area(db, obj)
    await log_event(db, user.id, "map_tools", f"Изменён объект {obj.name}", {"object_id": str(obj.id)})
    await db.commit()
    await db.refresh(obj)
    return await object_payload(db, obj)


async def recalc_area(db: AsyncSession, obj: LayerObject) -> None:
    if obj.is_point:
        obj.area_ha = 0.0
        return
    from sqlalchemy import text as sql_text

    value = await db.scalar(
        sql_text("SELECT ST_Area(ST_Transform(geom, 4326)::geography) FROM layer_objects WHERE id = :id"),
        {"id": obj.id},
    )
    obj.area_ha = float(value or 0) / 10_000


async def delete_object(db: AsyncSession, user: User, object_id: UUID) -> None:
    obj = await get_owned_object(db, user, object_id)
    await db.delete(obj)
    await log_event(db, user.id, "map_tools", f"Удалён объект {obj.name}")
    await db.commit()


async def merge_objects(db: AsyncSession, user: User, data: MergeRequest) -> dict[str, Any]:
    objs = []
    for oid in data.object_ids:
        objs.append(await get_owned_object(db, user, oid))
    layer_ids = {obj.layer_id for obj in objs}
    if len(layer_ids) != 1:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Можно объединять только объекты одного слоя")
    if any(obj.is_point for obj in objs):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Точечные объекты нельзя объединять")
    union_geom = await db.scalar(
        select(ST_Union(LayerObject.geom)).where(LayerObject.id.in_(data.object_ids))
    )
    keep = objs[0]
    keep.geom = union_geom
    for extra in objs[1:]:
        await db.delete(extra)
    await db.flush()
    await recalc_area(db, keep)
    await log_event(db, user.id, "map_tools", "Объединение полигонов", {"object_ids": [str(i) for i in data.object_ids]})
    await db.commit()
    await db.refresh(keep)
    return await object_payload(db, keep)


async def import_file(db: AsyncSession, user: User, upload: UploadFile) -> dict[str, Any]:
    filename = upload.filename or "import"
    data = await upload.read()
    features: list[dict[str, Any]] = []
    suffix = Path(filename).suffix.lower()
    if suffix in {".geojson", ".json"}:
        payload = json.loads(data.decode("utf-8"))
        if payload.get("type") == "FeatureCollection":
            features = payload.get("features") or []
        elif payload.get("type") == "Feature":
            features = [payload]
        else:
            features = [{"type": "Feature", "geometry": payload, "properties": {}}]
    elif suffix == ".zip":
        features = _features_from_shapefile_zip(data)
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Поддерживаются GeoJSON и Shapefile (.zip)")

    layer = Layer(
        user_id=user.id,
        name=f"Импорт: {filename}",
        color="#FF8F00",
        kind="import",
        source_filename=filename,
    )
    db.add(layer)
    await db.flush()
    xs: list[float] = []
    ys: list[float] = []
    for idx, feature in enumerate(features, start=1):
        geom = feature.get("geometry")
        if not geom:
            continue
        shapely_geom = shape(geom)
        if shapely_geom.is_empty:
            continue
        bounds = shapely_geom.bounds
        xs.extend([bounds[0], bounds[2]])
        ys.extend([bounds[1], bounds[3]])
        props = feature.get("properties") or {}
        obj = LayerObject(
            layer_id=layer.id,
            name=str(props.get("name") or props.get("NAME") or f"Объект {idx}"),
            number=idx,
            geom=wkb_element(shapely_geom, 4326),
            is_point=shapely_geom.geom_type == "Point",
            origin="manual",
        )
        db.add(obj)
    await db.commit()
    bbox = None
    if xs and ys:
        bbox = [min(xs), min(ys), max(xs), max(ys)]
    await log_event(db, user.id, "export", f"Импорт {filename}", {"layer_id": str(layer.id)}, commit=True)
    return {"layer": _layer_dict(layer, len(features)), "bbox": bbox}


def _features_from_shapefile_zip(data: bytes) -> list[dict[str, Any]]:
    import geopandas as gpd

    with tempfile.TemporaryDirectory() as tmp:
        zpath = Path(tmp) / "in.zip"
        zpath.write_bytes(data)
        with zipfile.ZipFile(zpath) as zf:
            zf.extractall(tmp)
        shp = next(Path(tmp).rglob("*.shp"), None)
        if shp is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="В архиве нет .shp")
        gdf = gpd.read_file(shp)
        if gdf.crs and gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(4326)
        return json.loads(gdf.to_json())["features"]


async def export_layers(db: AsyncSession, user: User, data: ExportRequest) -> tuple[bytes, str, str]:
    stmt = (
        select(Layer)
        .options(selectinload(Layer.objects), selectinload(Layer.folder))
        .where(Layer.user_id == user.id, Layer.is_visible.is_(True))
    )
    if data.layer_ids:
        stmt = stmt.where(Layer.id.in_(data.layer_ids))
    layers = (await db.execute(stmt)).scalars().unique().all()
    packed = []
    for layer in layers:
        objects = []
        for obj in layer.objects:
            geojson = json.loads((await db.scalar(select(ST_AsGeoJSON(obj.geom)))) or "{}")
            objects.append(
                {
                    "id": obj.id,
                    "name": obj.name,
                    "number": obj.number,
                    "geom": geojson,
                    "is_point": obj.is_point,
                    "origin": obj.origin,
                    "area_ha": obj.area_ha,
                }
            )
        packed.append(
            {
                "id": layer.id,
                "name": layer.name,
                "color": layer.color,
                "folder_name": layer.folder.name if layer.folder else None,
                "objects": objects,
            }
        )
    geojson = objects_to_geojson(packed)
    await log_event(
        db,
        user.id,
        "export",
        f"Экспорт слоёв ({data.format})",
        {"format": data.format, "count": len(packed)},
        commit=True,
    )
    if data.format == "geojson":
        return json.dumps(geojson, ensure_ascii=False).encode("utf-8"), "application/geo+json", "layers.geojson"
    if data.format == "kml":
        return geojson_to_kml(geojson), "application/vnd.google-earth.kml+xml", "layers.kml"
    if data.format == "shapefile":
        return geojson_to_shapefile_zip(geojson), "application/zip", "layers.zip"
    return geojson_to_svg(geojson), "image/svg+xml", "layers.svg"
