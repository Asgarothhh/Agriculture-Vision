from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_CONFIG = Path(__file__).resolve().parent / "config.yaml"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw is not None else default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw is not None else default


@dataclass
class ModelSettings:
    """Параметры загрузки модели и инференса."""

    checkpoint_path: Path = field(
        default_factory=lambda: _REPO_ROOT / "model/weights/best_iou.pth"
    )
    device: str = "auto"  # auto | cuda | cpu
    fp16: bool = True
    tile_size: int = 512
    threshold: float = 0.5
    tta: bool = False
    letterbox: bool = True
    sliding_stride: int = 384
    sliding_tta: bool = False
    # решение принимает модель; эвристики по RGB — только если включить явно
    pseudo_nir: str = "green"  # green | exg | red
    rgb_blend: float = 0.0
    keep_largest: bool = False
    rgb_fallback: bool = False
    mask_morph_open_px: int = 5
    max_side_px: int = 4096
    max_upload_bytes: int = 50 * 1024 * 1024
    headland_margin_px: int = 12
    polygon_simplify: float = 2.5
    min_polygon_area_px: float = 500.0
    # границы полей для карты: сглаживание рваного края маски
    field_mask_open_px: int = 3
    field_mask_close_px: int = 9
    field_mask_blur_px: int = 5
    field_smooth_px: float = 6.0
    field_simplify_px: float = 6.0
    field_min_area_px: float = 4000.0
    field_max_polygons: int = 200
    # деление сплошной пашни на отдельные участки по межам/дорогам на снимке
    split_parcels: bool = True
    parcel_ridge_quantile: float = 0.80
    parcel_boundary_sigma: float = 2.0
    include_geojson: bool = False
    geo_origin_lat: float = 55.75
    geo_origin_lon: float = 37.62
    geo_m_per_px: float = 0.05
    api_host: str = "0.0.0.0"
    api_port: int = 8080
    max_concurrent_inferences: int = 1

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> ModelSettings:
        known = {f.name for f in cls.__dataclass_fields__.values()}
        kwargs = {k: v for k, v in data.items() if k in known}
        if "checkpoint_path" in kwargs:
            kwargs["checkpoint_path"] = Path(kwargs["checkpoint_path"])
        return cls(**kwargs)

    def resolve_device(self) -> str:
        if self.device != "auto":
            return self.device
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"

    def fp16_enabled(self, device: str) -> bool:
        return self.fp16 and device.startswith("cuda")


def load_settings(config_path: str | Path | None = None) -> ModelSettings:
    path = Path(config_path) if config_path else _DEFAULT_CONFIG
    data: dict[str, Any] = {}
    if path.is_file():
        with path.open(encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        data = raw.get("serving", raw)

    settings = ModelSettings.from_mapping(data)

    ckpt = os.environ.get("MODEL_CHECKPOINT_PATH")
    if ckpt:
        settings.checkpoint_path = Path(ckpt)
    if not settings.checkpoint_path.is_absolute():
        settings.checkpoint_path = (_REPO_ROOT / settings.checkpoint_path).resolve()

    settings.fp16 = _env_bool("MODEL_FP16", settings.fp16)
    settings.device = os.environ.get("MODEL_DEVICE", settings.device)
    settings.api_port = _env_int("MODEL_API_PORT", settings.api_port)
    settings.max_side_px = _env_int("MODEL_MAX_SIDE_PX", settings.max_side_px)
    settings.threshold = _env_float("MODEL_THRESHOLD", settings.threshold)
    if os.environ.get("MODEL_TTA") is not None:
        settings.tta = _env_bool("MODEL_TTA", settings.tta)

    return settings
