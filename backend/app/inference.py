"""Инференс сегментации/классификации для FastAPI (переиспользует field_detecter)."""

from __future__ import annotations

import base64
import random
import sys
import time
from typing import Any

import cv2
import numpy as np

from paths import PLUGIN_DIR, SEGFORMER_WEIGHTS, YOLO_WEIGHTS, ensure_models_dir

# field_detecter импортируется как пакет из каталога плагина
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))

YOLO_CLASSES = {
    0: "field",
    1: "double_plant",
    2: "drydown",
    3: "endrow",
    4: "nutrient_deficiency",
    5: "planter_skip",
    6: "storm_damage",
    7: "water",
    8: "waterway",
    9: "weed_cluster",
}

CROP_CLASSES = [
    "wheat",
    "corn",
    "soybean",
    "sunflower",
    "rapeseed",
    "barley",
    "oat",
    "rice",
    "potato",
    "sugar_beet",
]

DEFAULT_SEGMENTATION_THRESHOLD = 0.4
DEFAULT_CLASSIFICATION_THRESHOLD = 0.6


def get_device_name() -> str:
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def available_segmentation_models() -> list[str]:
    models: list[str] = []
    if YOLO_WEIGHTS.is_file():
        models.append("yolo")
    if SEGFORMER_WEIGHTS.is_file():
        models.append("segformer")
    return models


def weights_status() -> dict[str, Any]:
    ensure_models_dir()
    return {
        "yolo": {
            "path": str(YOLO_WEIGHTS),
            "present": YOLO_WEIGHTS.is_file(),
        },
        "segformer": {
            "path": str(SEGFORMER_WEIGHTS),
            "present": SEGFORMER_WEIGHTS.is_file(),
        },
        "models_dir": str(ensure_models_dir()),
    }


def decode_image_bytes(image_bytes: bytes) -> np.ndarray:
    """PNG/JPEG/TIFF bytes → RGB uint8 H×W×3."""
    nparr = np.frombuffer(image_bytes, np.uint8)
    bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if bgr is not None:
        return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

    try:
        from PIL import Image
        import io

        img = Image.open(io.BytesIO(image_bytes))
        if getattr(img, "n_frames", 1) > 1:
            img.seek(0)
        if img.mode != "RGB":
            img = img.convert("RGB")
        return np.asarray(img, dtype=np.uint8)
    except Exception as exc:
        raise ValueError(
            "Не удалось декодировать изображение (ожидается PNG/JPEG/TIFF)"
        ) from exc


def run_segformer(
    rgb_image: np.ndarray,
    threshold: float,
    *,
    tta: bool = False,
    include_geojson: bool = False,
) -> dict[str, Any]:
    if not SEGFORMER_WEIGHTS.is_file():
        raise FileNotFoundError(
            f"Веса SegFormer не найдены: {SEGFORMER_WEIGHTS}. "
            f"Положите best_iou.pth в {ensure_models_dir()}"
        )

    import torch
    import torch.nn.functional as F
    from field_detecter.polygon import mask_to_navigable_polygon, polygon_to_geojson_feature
    from field_detecter.seg_infer import (
        load_rgb_nir_from_array,
        load_segformer_checkpoint,
        predict_prob,
        prob_to_mask,
    )

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    t0 = time.perf_counter()

    image_4ch = load_rgb_nir_from_array(rgb_image, None)
    model, meta = load_segformer_checkpoint(SEGFORMER_WEIGHTS, device=device)
    model.eval()

    if tta:
        prob = predict_prob(model, image_4ch, device, tta=True)
    else:
        x = torch.from_numpy(image_4ch).unsqueeze(0).to(device)
        use_amp = device.type == "cuda"
        with torch.no_grad():
            with torch.autocast(device_type="cuda", enabled=use_amp):
                logits = model(x).logits
            if logits.shape[-2:] != image_4ch.shape[-2:]:
                logits = F.interpolate(
                    logits.float(),
                    size=image_4ch.shape[-2:],
                    mode="bilinear",
                    align_corners=False,
                )
            else:
                logits = logits.float()
            prob = logits.softmax(dim=1)[0, 1].cpu().numpy().astype(np.float32)

    # Query threshold must win over ckpt/heuristic defaults (quantile ~0.4).
    mask, th_used, mask_info = prob_to_mask(
        prob,
        threshold,
        fixed_threshold=True,
        auto_raise_threshold=False,
    )
    poly_raw = mask_to_navigable_polygon(
        mask,
        headland_margin_px=12,
        simplify_tolerance=2.5,
        min_area_px=500.0,
    )

    polygon_points: list[tuple[int, int]] = []
    area_px = 0.0
    if poly_raw.get("valid"):
        polygon_points = [(int(p[0]), int(p[1])) for p in poly_raw["polygon_px"]]
        area_px = float(poly_raw["area_px"])

    h, w = rgb_image.shape[:2]
    inference_ms = (time.perf_counter() - t0) * 1000.0
    # Always report the query threshold when it was provided to the API path.
    threshold_used = float(threshold)

    result: dict[str, Any] = {
        "ok": True,
        "navigable": {
            "polygon_px": polygon_points,
            "area_px": area_px,
            "valid": bool(poly_raw.get("valid", False)),
        },
        "image_hw": [h, w],
        "checkpoint": str(SEGFORMER_WEIGHTS),
        "metrics": {
            "threshold_used": threshold_used,
            "area_frac": float(mask_info.get("area_frac", 0.0)),
            "prob_mean": float(mask_info.get("prob_mean", float(prob.mean()))),
            "prob_std": float(mask_info.get("prob_std", float(prob.std()))),
            "mode": "tta" if tta else "prob_fixed",
            "inference_ms": round(inference_ms, 2),
            "fp16": device.type == "cuda",
            "device": device.type,
            "ckpt_epoch": meta.get("epoch"),
            "mask_threshold_applied": float(th_used),
        },
        "mode": "api",
    }

    if include_geojson and polygon_points:
        result["geojson"] = {
            "type": "FeatureCollection",
            "features": [
                polygon_to_geojson_feature(
                    polygon_points,
                    origin_lat=0.0,
                    origin_lon=0.0,
                )
            ],
        }

    del model
    if device.type == "cuda":
        torch.cuda.empty_cache()

    return result


def run_yolo(
    rgb_image: np.ndarray,
    threshold: float,
    *,
    include_geojson: bool = False,
) -> dict[str, Any]:
    if not YOLO_WEIGHTS.is_file():
        raise FileNotFoundError(
            f"Веса YOLO не найдены: {YOLO_WEIGHTS}. "
            f"Положите yolo_best.pt в {ensure_models_dir()}"
        )

    from ultralytics import YOLO

    t0 = time.perf_counter()
    model = YOLO(str(YOLO_WEIGHTS))
    outputs = model.predict(
        source=rgb_image,
        imgsz=640,
        conf=threshold,
        iou=0.5,
        verbose=False,
    )
    inference_ms = (time.perf_counter() - t0) * 1000.0

    detections: list[dict[str, Any]] = []
    res = outputs[0]
    if res.boxes is not None and len(res.boxes) > 0:
        boxes = res.boxes.cpu().numpy()
        masks_xy = res.masks.xy if res.masks is not None else []

        for idx, box in enumerate(boxes):
            class_id = int(box.cls[0])
            conf = float(box.conf[0])
            label = YOLO_CLASSES.get(class_id, f"class_{class_id}")
            xyxy = [float(v) for v in box.xyxy[0].tolist()]

            polygon_points: list[tuple[int, int]] = []
            area_px = 0.0
            if idx < len(masks_xy) and len(masks_xy[idx]) > 0:
                polygon_points = [(int(x), int(y)) for x, y in masks_xy[idx]]
                contour_array = np.array(polygon_points, dtype=np.int32)
                area_px = float(cv2.contourArea(contour_array))
            else:
                x1, y1, x2, y2 = [int(v) for v in xyxy]
                polygon_points = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
                area_px = float(max(0, x2 - x1) * max(0, y2 - y1))

            det: dict[str, Any] = {
                "label": label,
                "confidence": conf,
                "polygon_px": polygon_points,
                "area_px": area_px,
                "bbox_xyxy": [int(v) for v in xyxy],
                "valid": area_px > 0,
            }
            detections.append(det)

    h, w = rgb_image.shape[:2]
    result: dict[str, Any] = {
        "ok": True,
        "detections": detections,
        "image_hw": [h, w],
        "checkpoint": str(YOLO_WEIGHTS),
        "metrics": {
            "threshold_used": threshold,
            "area_frac": float(sum(d["area_px"] for d in detections) / max(1, h * w)),
            "prob_mean": float(
                np.mean([d["confidence"] for d in detections]) if detections else 0.0
            ),
            "prob_std": float(
                np.std([d["confidence"] for d in detections]) if detections else 0.0
            ),
            "mode": "standard",
            "inference_ms": round(inference_ms, 2),
            "fp16": False,
            "device": get_device_name(),
        },
        "mode": "api",
    }

    if include_geojson:
        from field_detecter.polygon import polygon_to_geojson_feature

        features = []
        for det in detections:
            if det.get("valid") and det.get("polygon_px"):
                feat = polygon_to_geojson_feature(
                    det["polygon_px"],
                    origin_lat=0.0,
                    origin_lon=0.0,
                )
                feat["properties"]["label"] = det["label"]
                feat["properties"]["confidence"] = det["confidence"]
                features.append(feat)
        result["geojson"] = {"type": "FeatureCollection", "features": features}

    del model
    return result


def run_segmentation(
    image_bytes: bytes,
    architecture: str = "yolo",
    threshold: float | None = None,
    tta: bool = False,
    include_geojson: bool = False,
) -> dict[str, Any]:
    threshold = (
        DEFAULT_SEGMENTATION_THRESHOLD if threshold is None else float(threshold)
    )
    architecture = architecture.lower().strip()
    rgb = decode_image_bytes(image_bytes)

    if architecture == "segformer":
        return run_segformer(
            rgb, threshold, tta=tta, include_geojson=include_geojson
        )
    if architecture == "yolo":
        return run_yolo(rgb, threshold, include_geojson=include_geojson)

    raise ValueError(
        f"Неизвестная architecture={architecture!r}. Допустимо: yolo, segformer"
    )


def run_classification(
    image_base64: str,
    threshold: float | None = None,
) -> dict[str, Any]:
    """Stub-классификатор (как LocalClassifier), живой endpoint."""
    threshold = (
        DEFAULT_CLASSIFICATION_THRESHOLD if threshold is None else float(threshold)
    )

    # Валидация base64 (демо-stub всё равно не использует пиксели)
    if not image_base64 or not str(image_base64).strip():
        raise ValueError("image_base64 пустой")
    try:
        raw = base64.b64decode(image_base64, validate=False)
        if len(raw) < 8:
            raise ValueError("image_base64 слишком короткий")
    except Exception as exc:
        raise ValueError(f"Некорректный image_base64: {exc}") from exc

    probs = [random.random() for _ in CROP_CLASSES]
    total = sum(probs) or 1.0
    probs = [p / total for p in probs]
    items = [
        {"crop_class": cls, "probability": round(p, 4)}
        for cls, p in zip(CROP_CLASSES, probs)
    ]
    items.sort(key=lambda x: x["probability"], reverse=True)
    predicted = items[0]["crop_class"]
    confidence = items[0]["probability"]

    return {
        "ok": True,
        "predicted_class": predicted,
        "confidence": confidence,
        "probabilities": items,
        "requires_review": confidence < threshold,
        "threshold_used": threshold,
        "mode": "api-stub",
        "classifier_loaded": False,
    }
