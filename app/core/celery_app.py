from __future__ import annotations

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "agrovision",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks_service.workers"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_queue=settings.celery_queue_cpu,
    task_routes={
        "app.tasks_service.workers.run_inference": {"queue": settings.celery_queue_gpu},
        "app.tasks_service.workers.export_layers_task": {"queue": settings.celery_queue_cpu},
    },
)
