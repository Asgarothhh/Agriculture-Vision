"""
Pydantic-схемы для API запросов и ответов.
"""

from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field


class SegmentRequest(BaseModel):
    """Параметры запроса на сегментацию."""
    threshold: float | None = Field(
        None, ge=0.0, le=1.0,
        description="Порог уверенности (0.0–1.0). Если не указан — берётся из настроек.",
    )
    tta: bool | None = Field(
        None,
        description="Test-Time Augmentation — повышает качество, но медленнее (только YOLO).",
    )
    use_sliding: bool = Field(
        False,
        description="Использовать скользящее окно для больших изображений (только YOLO).",
    )
    headland_margin_px: int | None = Field(
        None, ge=0,
        description="Отступ от краёв изображения в пикселях.",
    )
    include_mask_png: bool = Field(
        False,
        description="Включить бинарную маску сегментации в ответ (base64 PNG).",
    )
    include_overlay: bool = Field(
        False,
        description="Включить визуализацию результата (маски/полигоны на оригинале) в ответ (base64 PNG).",
    )
    include_geojson: bool | None = Field(
        None,
        description="Включить GeoJSON-представление полигонов.",
    )


class SegmentMetrics(BaseModel):
    """Метрики выполнения инференса."""
    threshold_used: float = Field(..., description="Фактический порог уверенности")
    area_frac: float = Field(..., description="Доля площади изображения, покрытая маской (0.0–1.0)")
    prob_mean: float = Field(..., description="Средняя уверенность по всем детекциям")
    prob_std: float = Field(..., description="Стандартное отклонение уверенности")
    mode: str = Field(..., description="Режим инференса: standard | tta | sliding")
    inference_ms: float = Field(..., description="Время инференса в миллисекундах")
    fp16: bool = Field(..., description="Использовался ли FP16")
    device: str = Field(..., description="Устройство инференса (cpu / cuda:N)")


class HealthResponse(BaseModel):
    """Ответ на health-check."""
    status: str = Field(..., description="healthy или unhealthy")
    model_loaded: bool = Field(..., description="Загружена ли модель")
    device: str | None = Field(None, description="Устройство (cpu/cuda)")
    fp16: bool | None = Field(None, description="FP16 активен")
    checkpoint: str | None = Field(None, description="Путь к чекпоинту модели")


class PolygonPayload(BaseModel):
    """Полигон в пиксельных координатах."""
    polygon_px: list[tuple[int, int]] = Field(
        ..., description="Список точек полигона [(x1,y1), (x2,y2), ...]"
    )
    area_px: float = Field(..., description="Площадь полигона в квадратных пикселях")
    valid: bool = Field(..., description="Корректен ли полигон (area > 0)")


class SegmentResponse(BaseModel):
    """Ответ от SegFormer-сегментации."""
    ok: bool = True
    navigable: PolygonPayload = Field(..., description="Полигон сегментированной области")
    geojson: dict[str, Any] | None = Field(None, description="GeoJSON-представление (если запрошено)")
    mask_png_base64: str | None = Field(
        None, description="Бинарная маска сегментации в base64 PNG (если запрошено)"
    )
    overlay_png_base64: str | None = Field(
        None, description="Визуализация: маска наложена на оригинал в base64 PNG (если запрошено)"
    )
    image_hw: tuple[int, int] = Field(..., description="Размеры исходного изображения (H, W)")
    checkpoint: str = Field(..., description="Путь к чекпоинту модели")
    val_metrics: dict[str, Any] | None = Field(None, description="Метрики качества модели")
    metrics: SegmentMetrics = Field(..., description="Метрики выполнения запроса")


class JobStatusResponse(BaseModel):
    """Статус асинхронного задания (для будущей очереди)."""
    job_id: str
    status: str
    position: int | None = None
    result: SegmentResponse | None = None
    error: str | None = None


class YoloDetectionPayload(BaseModel):
    """Результат детекции одного объекта YOLO."""
    label: str = Field(..., description="Имя класса объекта")
    confidence: float = Field(..., description="Уверенность детекции (0.0–1.0)")
    polygon_px: list[tuple[int, int]] = Field(
        ..., description="Полигон маски объекта в пикселях"
    )
    area_px: float = Field(..., description="Площадь маски в квадратных пикселях")
    bbox_xyxy: list[int] = Field(
        ..., description="Bounding box [x1, y1, x2, y2]"
    )
    valid: bool = Field(..., description="Валидность детекции (area > 0)")


class YoloSegmentResponse(BaseModel):
    """Ответ от YOLO-сегментации."""
    ok: bool = True
    detections: list[YoloDetectionPayload] = Field(
        ..., description="Список обнаруженных объектов"
    )
    geojson: dict[str, Any] | None = Field(None, description="GeoJSON-представление (если запрошено)")
    mask_png_base64: str | None = Field(
        None, description="Бинарная маска сегментации в base64 PNG (если запрошено)"
    )
    overlay_png_base64: str | None = Field(
        None, description="Визуализация: маски наложены на оригинал в base64 PNG (если запрошено)"
    )
    image_hw: tuple[int, int] = Field(..., description="Размеры исходного изображения (H, W)")
    checkpoint: str = Field(..., description="Путь к чекпоинту модели")
    val_metrics: dict[str, Any] | None = Field(None, description="Метрики качества модели")
    metrics: SegmentMetrics = Field(..., description="Метрики выполнения запроса")


class YoloJobStatusResponse(BaseModel):
    """Статус асинхронного YOLO-задания."""
    job_id: str
    status: str
    position: int | None = None
    result: YoloSegmentResponse | None = None
    error: str | None = None
