from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class MLParams(BaseModel):
    model: Literal["yolo_seg_26", "segformer"] = "segformer"
    confidence: float = Field(default=0.5, ge=0.05, le=0.95)
    aoi: dict[str, Any] | None = None


class TaskResponse(BaseModel):
    id: UUID
    model_name: str
    status: str
    progress: int
    error: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    confidence_threshold: float
    image_id: UUID | None = None


class ToLayersRequest(BaseModel):
    class_ids: list[int] | None = None
