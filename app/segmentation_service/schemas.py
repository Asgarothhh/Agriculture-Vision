from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SegmentRequest(BaseModel):
    threshold: float | None = None
    tta: bool | None = None
    use_sliding: bool = False
    headland_margin_px: int | None = None
    include_mask_png: bool = False
    include_geojson: bool | None = None


class PolygonPayload(BaseModel):
    polygon_px: list[tuple[int, int]]
    area_px: float
    valid: bool


class PolygonItem(BaseModel):
    polygon_px: list[tuple[int, int]]
    area_px: float
    valid: bool = True
    label: str = "field"


class SegmentMetrics(BaseModel):
    threshold_used: float
    area_frac: float
    prob_mean: float
    prob_std: float
    mode: str
    inference_ms: float
    fp16: bool
    device: str


class SegmentResponse(BaseModel):
    ok: bool = True
    navigable: PolygonPayload
    polygons: list[PolygonItem] = Field(default_factory=list)
    geojson: dict[str, Any] | None = None
    mask_png_base64: str | None = None
    image_hw: tuple[int, int]
    checkpoint: str
    val_metrics: dict[str, Any] | None = None
    metrics: SegmentMetrics


class HealthResponse(BaseModel):
    status: str
    model_loaded: bool
    device: str | None = None
    fp16: bool | None = None
    checkpoint: str | None = None
    available_models: list[str] = Field(default_factory=list)
    hint: str | None = None


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    position: int | None = None
    result: SegmentResponse | None = None
    error: str | None = None
