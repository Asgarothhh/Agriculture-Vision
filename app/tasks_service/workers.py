from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from geoalchemy2.shape import to_shape
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.celery_app import celery_app
from app.core.config import get_settings
from app.core.database import SyncSessionLocal
from app.core.storage import download_bytes
from app.ml_service.runtime import infer_sync, load_models
from app.ml_service.postprocess import persist_inference
from app.ml_service.schemas import InferenceRequest
from app.tasks_service.models import ProcessingTask
from app.tasks_service.service import enforce_task_limit
from app.users_service.models import ActivityLog
from celery.signals import worker_process_init

app = celery_app


@worker_process_init.connect
def _load_weights(**kwargs) -> None:
    load_models()


def _utcnow() -> datetime:
    return datetime.now(UTC)


@celery_app.task(name="app.tasks_service.workers.run_inference")
def run_inference(task_id: str, transform: list[float] | None = None, pixel_space: bool = False) -> None:
    session = SyncSessionLocal()
    try:
        task = session.scalar(
            select(ProcessingTask)
            .options(selectinload(ProcessingTask.image))
            .where(ProcessingTask.id == UUID(task_id))
        )
        if task is None or task.image is None:
            return
        task.status = "PROCESSING"
        task.progress = 10
        session.commit()

        data = download_bytes(task.image.file_path)
        task.progress = 30
        session.commit()

        aoi = None
        if task.aoi is not None:
            from shapely.geometry import mapping

            aoi = mapping(to_shape(task.aoi))

        request = InferenceRequest(
            model=task.model_name,  # type: ignore[arg-type]
            confidence=task.confidence_threshold,
            aoi=aoi,
            crs=task.image.crs,
            width=task.image.width,
            height=task.image.height,
            transform=transform,
        )
        response = infer_sync(data, task.image.file_path.split("/")[-1], request)
        task.progress = 70
        session.commit()

        persist_inference(
            session,
            task.image,
            response,
            threshold=task.confidence_threshold,
            transform=transform,
            pixel_space=pixel_space,
        )
        task.status = "COMPLETED"
        task.progress = 100
        task.completed_at = _utcnow()
        task.error = None
        enforce_task_limit(session, task.user_id, get_settings().max_saved_tasks)
        session.add(
            ActivityLog(
                user_id=task.user_id,
                category="upload_processing",
                action="Обработка снимка завершена",
                payload={"task_id": str(task.id), "model": task.model_name},
            )
        )
        session.commit()
    except Exception as exc:
        session.rollback()
        task = session.scalar(select(ProcessingTask).where(ProcessingTask.id == UUID(task_id)))
        if task is not None:
            task.status = "FAILED"
            task.error = str(exc)
            task.progress = 0
            session.add(
                ActivityLog(
                    user_id=task.user_id,
                    category="upload_processing",
                    action="Ошибка обработки снимка",
                    payload={"task_id": str(task.id), "error": str(exc)[:500]},
                )
            )
            session.commit()
        raise
    finally:
        session.close()


@celery_app.task(name="app.tasks_service.workers.export_layers_task")
def export_layers_task(payload: dict) -> dict:
    return payload
