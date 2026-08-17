"""Полный пайплайн: RGB(+NIR) → маска → полигон → ответ API"""

from __future__ import annotations

import base64
import io
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from field_detecter.polygon import (
    mask_to_field_polygons,
    mask_to_navigable_polygon,
    polygon_to_geojson_feature,
)
from field_detecter.seg_infer import (
    crop_mask_from_letterbox,
    letterbox_image,
    load_rgb_nir_from_array,
    prob_to_mask,
)
from model import inference as infer_fp16
from model.runtime import SegmentationRuntime
from model.schemas import PolygonItem, PolygonPayload, SegmentMetrics, SegmentRequest, SegmentResponse
from model.settings import ModelSettings


def _read_rgb_nir(
    rgb_path: str | Path,
    nir_path: str | Path | None,
    max_side: int,
) -> tuple[np.ndarray, np.ndarray | None]:
    bgr = cv2.imread(str(rgb_path))
    if bgr is None:
        raise FileNotFoundError(rgb_path)
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    rgb = _limit_image_side(rgb, max_side)
    nir: np.ndarray | None = None
    if nir_path and Path(nir_path).is_file():
        nir = cv2.imread(str(nir_path), cv2.IMREAD_GRAYSCALE)
        if nir is not None:
            nir = cv2.resize(
                nir,
                (rgb.shape[1], rgb.shape[0]),
                interpolation=cv2.INTER_LINEAR,
            )
    return rgb, nir


def _limit_image_side(rgb: np.ndarray, max_side: int) -> np.ndarray:
    h, w = rgb.shape[:2]
    side = max(h, w)
    if side <= max_side:
        return rgb
    scale = max_side / side
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    return cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_LINEAR)


def _prepare_4ch(
    rgb: np.ndarray,
    nir: np.ndarray | None,
    *,
    tile_size: int,
    letterbox: bool,
    pseudo_nir: str = "green",
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict | None]:
    letterbox_meta = None
    rgb_infer = rgb
    if letterbox:
        rgb_infer, nir_lb, letterbox_meta = letterbox_image(rgb, nir, tile_size)
        nir = nir_lb
    image_4ch = load_rgb_nir_from_array(rgb_infer, nir, pseudo_nir=pseudo_nir)
    return rgb_infer, image_4ch, rgb, letterbox_meta


def _mask_to_png_b64(mask: np.ndarray) -> str:
    img = Image.fromarray((mask > 0).astype(np.uint8) * 255)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.standard_b64encode(buf.getvalue()).decode("ascii")


def run_segmentation(
    runtime: SegmentationRuntime,
    *,
    rgb_path: str | Path | None = None,
    nir_path: str | Path | None = None,
    rgb: np.ndarray | None = None,
    nir: np.ndarray | None = None,
    request: SegmentRequest | None = None,
) -> SegmentResponse:
    """Сегментация одного кадра (файлы или массивы uint8)."""
    if not runtime.is_loaded:
        runtime.load()

    req = request or SegmentRequest()
    settings: ModelSettings = runtime.settings
    device = runtime.device
    fp16 = settings.fp16_enabled(str(device))

    threshold = req.threshold if req.threshold is not None else settings.threshold
    ckpt_th = runtime.meta.get("checkpoint_threshold")
    if ckpt_th is not None and req.threshold is None:
        threshold = float(ckpt_th)

    tta = req.tta if req.tta is not None else settings.tta
    tile_size = int(runtime.meta.get("tile_size", settings.tile_size))

    t0 = time.perf_counter()

    if rgb is None:
        if rgb_path is None:
            raise ValueError("rgb_path or rgb array is required")
        rgb, nir = _read_rgb_nir(rgb_path, nir_path, settings.max_side_px)
    else:
        rgb = _limit_image_side(rgb, settings.max_side_px)
        if nir is not None:
            nir = cv2.resize(
                nir,
                (rgb.shape[1], rgb.shape[0]),
                interpolation=cv2.INTER_LINEAR,
            )

    # Снимок крупнее тайла режем скользящим окном в нативном разрешении:
    # letterbox сжал бы весь кадр до tile_size и убил детализацию границ.
    h0, w0 = rgb.shape[:2]
    use_sliding = req.use_sliding or max(h0, w0) > tile_size

    if use_sliding:
        rgb_infer = rgb
        letterbox_meta = None
        image_4ch = load_rgb_nir_from_array(rgb, nir, pseudo_nir=settings.pseudo_nir)
        prob = infer_fp16.predict_prob_sliding(
            runtime.model,
            image_4ch,
            device,
            tile=tile_size,
            stride=settings.sliding_stride,
            tta=settings.sliding_tta if req.tta is None else tta,
            fp16=fp16,
        )
    else:
        rgb_infer, image_4ch, _, letterbox_meta = _prepare_4ch(
            rgb,
            nir,
            tile_size=tile_size,
            letterbox=settings.letterbox,
            pseudo_nir=settings.pseudo_nir,
        )
        prob = infer_fp16.predict_prob(
            runtime.model, image_4ch, device, tta=tta, fp16=fp16
        )

    mask, th_used, info = prob_to_mask(
        prob,
        threshold,
        rgb_uint8=rgb_infer,
        rgb_blend=settings.rgb_blend,
        keep_largest=settings.keep_largest,
        morph_open=settings.mask_morph_open_px,
        rgb_fallback=settings.rgb_fallback,
    )
    info["mode"] = f"{info.get('mode', 'prob_only')}{'_sliding' if use_sliding else ''}"
    if letterbox_meta is not None:
        mask = crop_mask_from_letterbox(mask, letterbox_meta)
        prob = crop_mask_from_letterbox(prob, letterbox_meta)

    headland = (
        req.headland_margin_px
        if req.headland_margin_px is not None
        else settings.headland_margin_px
    )
    poly_raw = mask_to_navigable_polygon(
        mask,
        headland_margin_px=headland,
        simplify_tolerance=settings.polygon_simplify,
        min_area_px=settings.min_polygon_area_px,
    )
    navigable = PolygonPayload(
        polygon_px=[tuple(p) for p in poly_raw["polygon_px"]],
        area_px=float(poly_raw["area_px"]),
        valid=bool(poly_raw["valid"]),
    )
    field_polys = mask_to_field_polygons(
        mask,
        rgb if mask.shape[:2] == rgb.shape[:2] else rgb_infer,
        split_parcels=settings.split_parcels,
        ridge_quantile=settings.parcel_ridge_quantile,
        boundary_sigma=settings.parcel_boundary_sigma,
        simplify_tolerance=settings.field_simplify_px,
        min_area_px=settings.field_min_area_px,
        max_polygons=settings.field_max_polygons,
        open_px=settings.field_mask_open_px,
        close_px=settings.field_mask_close_px,
        blur_px=settings.field_mask_blur_px,
        smooth_px=settings.field_smooth_px,
    )
    polygons = [
        PolygonItem(
            polygon_px=[tuple(p) for p in item["polygon_px"]],
            area_px=float(item["area_px"]),
            valid=len(item["polygon_px"]) >= 3,
            label="field",
        )
        for item in field_polys
        if len(item["polygon_px"]) >= 3
    ]

    include_geo = (
        req.include_geojson
        if req.include_geojson is not None
        else settings.include_geojson
    )
    geojson = None
    if include_geo and navigable.valid:
        geojson = polygon_to_geojson_feature(
            navigable.polygon_px,
            origin_lat=settings.geo_origin_lat,
            origin_lon=settings.geo_origin_lon,
            m_per_px=settings.geo_m_per_px,
        )

    mask_b64 = _mask_to_png_b64(mask) if req.include_mask_png else None
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    out_h, out_w = mask.shape[:2]
    metrics = SegmentMetrics(
        threshold_used=float(info.get("threshold_used", th_used)),
        area_frac=float(info.get("area_frac", float(mask.mean()))),
        prob_mean=float(info.get("prob_mean", prob.mean() if prob is not None else 0.0)),
        prob_std=float(info.get("prob_std", prob.std() if prob is not None else 0.0)),
        mode=str(info.get("mode", "unknown")),
        inference_ms=elapsed_ms,
        fp16=fp16,
        device=str(device),
    )

    return SegmentResponse(
        navigable=navigable,
        polygons=polygons,
        geojson=geojson,
        mask_png_base64=mask_b64,
        image_hw=(out_h, out_w),
        checkpoint=str(runtime.meta.get("checkpoint_path", "")),
        val_metrics=runtime.meta.get("val_metrics"),
        metrics=metrics,
    )
