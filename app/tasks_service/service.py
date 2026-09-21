from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import HTTPException, UploadFile, status
from geoalchemy2.functions import ST_AsGeoJSON, ST_Transform
from shapely.geometry import shape
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.activity_service.service import log_event
from app.core.config import get_settings
from app.core.geo import wkb_element
from app.core.storage import upload_bytes
from app.layers_service.models import Layer, LayerObject
from app.ml_service.models import PointObject, PolygonObject
from app.ml_service.postprocess import results_to_geojson
from app.tasks_service.models import Image, ProcessingTask
from app.users_service.models import User

ALLOWED_EXT = {".tif", ".tiff", ".png", ".jpg", ".jpeg"}
ALLOWED_MODELS = {"yolo_seg_26", "segformer"}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _read_raster_meta(data: bytes, filename: str) -> dict[str, Any]:
    try:
        import rasterio
        from rasterio.io import MemoryFile

        with MemoryFile(data) as mem:
            with mem.open() as src:
                crs = src.crs.to_string() if src.crs else "EPSG:4326"
                transform = list(src.transform.to_gdal()) if src.transform else None
                bounds = src.bounds
                coverage = None
                try:
                    from shapely.geometry import box

                    coverage = abs((bounds.right - bounds.left) * (bounds.top - bounds.bottom))
                except Exception:
                    coverage = None
                count = src.count
                if count >= 4:
                    image_type = "Multispectral"
                elif count == 1:
                    image_type = "NIR"
                else:
                    image_type = "RGB"
                return {
                    "crs": crs,
                    "width": src.width,
                    "height": src.height,
                    "transform": transform,
                    "coverage_area": coverage,
                    "image_type": image_type,
                    "is_valid": True,
                }
    except Exception:
        from PIL import Image as PILImage

        img = PILImage.open(io.BytesIO(data))
        return {
            "crs": "EPSG:4326",
            "width": img.width,
            "height": img.height,
            "transform": None,
            "coverage_area": None,
            "image_type": "RGB",
            "is_valid": True,
        }


async def create_task(
    db: AsyncSession,
    user: User,
    upload: UploadFile,
    model: str,
    confidence: float,
    aoi: dict[str, Any] | None,
) -> ProcessingTask:
    settings = get_settings()
    filename = upload.filename or "image.tif"
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXT:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Разрешены .tif/.tiff/.png/.jpg")
    if model not in ALLOWED_MODELS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Неизвестная модель")
    data = await upload.read()
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Файл слишком большой")
    meta = _read_raster_meta(data, filename)

    aoi_elem = None
    if aoi:
        aoi_elem = wkb_element(shape(aoi) if aoi.get("type") != "Feature" else shape(aoi["geometry"]), 4326)

    task = ProcessingTask(
        user_id=user.id,
        model_name=model,
        confidence_threshold=confidence,
        aoi=aoi_elem,
        status="PENDING",
        progress=0,
        expires_at=_utcnow() + timedelta(days=30),
    )
    db.add(task)
    await db.flush()
    key = f"uploads/{user.id}/{task.id}/{filename}"
    try:
        upload_bytes(key, data, upload.content_type or "application/octet-stream")
    except Exception as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Object storage unavailable") from exc

    image = Image(
        task_id=task.id,
        file_path=key,
        image_type=meta["image_type"],
        crs=meta["crs"],
        coverage_area=meta["coverage_area"],
        is_valid=meta["is_valid"],
        width=meta["width"],
        height=meta["height"],
    )
    db.add(image)
    await log_event(
        db,
        user.id,
        "upload_processing",
        f"Загрузка снимка {filename}",
        {"task_id": str(task.id), "model": model},
    )
    await db.commit()
    try:
        from app.core.celery_app import celery_app

        celery_app.send_task(
            "app.tasks_service.workers.run_inference",
            args=[str(task.id), meta.get("transform")],
            kwargs={"pixel_space": bool(meta.get("transform"))},
        )
    except Exception as exc:
        task.status = "FAILED"
        task.error = f"Queue unavailable: {exc}"
        await db.commit()
    return await db.scalar(
        select(ProcessingTask)
        .options(selectinload(ProcessingTask.image))
        .where(ProcessingTask.id == task.id)
    )


def task_to_dict(task: ProcessingTask) -> dict[str, Any]:
    return {
        "id": task.id,
        "model_name": task.model_name,
        "status": task.status,
        "progress": task.progress,
        "error": task.error,
        "created_at": task.created_at,
        "completed_at": task.completed_at,
        "confidence_threshold": task.confidence_threshold,
        "image_id": task.image.id if task.image else None,
    }


async def list_tasks(
    db: AsyncSession,
    user: User,
    *,
    status_filter: str | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    stmt = select(ProcessingTask).options(selectinload(ProcessingTask.image)).where(
        ProcessingTask.user_id == user.id
    )
    if status_filter:
        stmt = stmt.where(ProcessingTask.status == status_filter)
    stmt = stmt.order_by(ProcessingTask.created_at.desc())
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.limit(limit).offset(offset))).scalars().all()
    return {"items": [task_to_dict(t) for t in rows], "total": int(total), "limit": limit, "offset": offset}


async def get_task(db: AsyncSession, user: User, task_id: UUID) -> ProcessingTask:
    task = (
        await db.execute(
            select(ProcessingTask)
            .options(selectinload(ProcessingTask.image))
            .where(ProcessingTask.id == task_id, ProcessingTask.user_id == user.id)
        )
    ).scalar_one_or_none()
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


async def delete_task(db: AsyncSession, user: User, task_id: UUID) -> None:
    task = await get_task(db, user, task_id)
    if task.status not in {"PENDING", "FAILED"}:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Можно удалить только PENDING или FAILED")
    await db.delete(task)
    await db.commit()


async def publish_to_layers(
    db: AsyncSession,
    user: User,
    task: ProcessingTask,
    class_ids: list[int] | None,
) -> dict[str, Any]:
    if task.status != "COMPLETED" or task.image is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Нет завершённого результата")
    layers_stmt = select(Layer).where(Layer.user_id == user.id, Layer.kind == "auto", Layer.is_visible.is_(True))
    layers = (await db.execute(layers_stmt)).scalars().all()
    by_class = {layer.class_id: layer for layer in layers if layer.class_id is not None}
    allowed = set(class_ids) if class_ids else set(by_class)
    created = 0

    polygons = (
        await db.execute(select(PolygonObject).where(PolygonObject.image_id == task.image.id))
    ).scalars().all()
    for poly in polygons:
        if poly.class_id not in allowed or poly.class_id not in by_class:
            continue
        layer = by_class[poly.class_id]
        geo = await db.scalar(select(ST_AsGeoJSON(ST_Transform(poly.geom, 4326))))
        if not geo:
            continue
        number = (
            await db.scalar(
                select(func.coalesce(func.max(LayerObject.number), 0)).where(LayerObject.layer_id == layer.id)
            )
            or 0
        )
        db.add(
            LayerObject(
                layer_id=layer.id,
                source_image_id=task.image.id,
                name=f"{layer.name} {int(number) + 1}",
                number=int(number) + 1,
                geom=wkb_element(json.loads(geo), 4326),
                is_point=False,
                origin="auto",
            )
        )
        created += 1

    points = (
        await db.execute(select(PointObject).where(PointObject.image_id == task.image.id))
    ).scalars().all()
    for point in points:
        if point.class_id not in allowed or point.class_id not in by_class:
            continue
        layer = by_class[point.class_id]
        geo = await db.scalar(select(ST_AsGeoJSON(ST_Transform(point.geom, 4326))))
        if not geo:
            continue
        number = (
            await db.scalar(
                select(func.coalesce(func.max(LayerObject.number), 0)).where(LayerObject.layer_id == layer.id)
            )
            or 0
        )
        db.add(
            LayerObject(
                layer_id=layer.id,
                source_image_id=task.image.id,
                name=f"{layer.name} {int(number) + 1}",
                number=int(number) + 1,
                geom=wkb_element(json.loads(geo), 4326),
                is_point=True,
                origin="auto",
            )
        )
        created += 1

    await log_event(db, user.id, "upload_processing", "Публикация результата на карту", {"task_id": str(task.id)})
    await db.commit()
    return {"created": created}


def enforce_task_limit(session, user_id: UUID, limit: int) -> None:
    rows = session.scalars(
        select(ProcessingTask)
        .where(ProcessingTask.user_id == user_id, ProcessingTask.status == "COMPLETED")
        .order_by(ProcessingTask.completed_at.desc())
    ).all()
    for extra in rows[limit:]:
        session.delete(extra)
