from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class InferenceRequest(BaseModel):
    model: Literal["yolo_seg_26", "segformer"]
    confidence: float = Field(ge=0.05, le=0.95, default=0.5)
    aoi: dict[str, Any] | None = None
    crs: str = "EPSG:4326"
    width: int | None = None
    height: int | None = None
    transform: list[float] | None = None


class InferenceFeature(BaseModel):
    class_id: int
    confidence: float
    geometry: dict[str, Any]
    radius_approx: float | None = None
    area_approx: float | None = None
    crop_probabilities: dict[int, float] | None = None


class InferenceResponse(BaseModel):
    model: str
    polygons: list[InferenceFeature] = Field(default_factory=list)
    points: list[InferenceFeature] = Field(default_factory=list)
