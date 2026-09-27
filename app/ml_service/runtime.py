from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

from app.core.config import get_settings
from app.ml_service.schemas import InferenceFeature, InferenceRequest, InferenceResponse

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]


class ModelRuntime:
    """Loads fine-tuned YOLO / SegFormer weights from disk and runs inference in-process."""

    def __init__(self) -> None:
        self._yolo = None
        self._segformer = None
        self._loaded: dict[str, bool] = {"yolo_seg_26": False, "segformer": False}
        self._paths: dict[str, str | None] = {"yolo_seg_26": None, "segformer": None}
        self._errors: dict[str, str] = {}

    def reset(self) -> None:
        self._yolo = None
        self._segformer = None
        self._loaded = {"yolo_seg_26": False, "segformer": False}
        self._paths = {"yolo_seg_26": None, "segformer": None}
        self._errors = {}

    def _resolve(self, configured: str, *fallbacks: str) -> Path | None:
        candidates = [configured, *fallbacks]
        for raw in candidates:
            path = Path(raw)
            if not path.is_absolute():
                path = ROOT / path
            if path.is_dir():
                logger.warning(
                    "Skipping directory %s — pack with: python scripts/pack_segformer_weights.py",
                    path,
                )
                continue
            if path.is_file() and path.stat().st_size > 0:
                return path
        return None

    def load_models(self) -> dict[str, Any]:
        settings = get_settings()
        yolo_path = self._resolve(
            settings.yolo_weights_path,
            "config/yolo_best.pt",
        )
        seg_path = self._resolve(
            settings.segformer_weights_path,
            "config/segformer_best.pt",
            "config/segformer_best/best_iou",
            "app/segmentation_service/weights/best_iou.pth",
        )
        if yolo_path is not None:
            self._paths["yolo_seg_26"] = str(yolo_path)
            try:
                from ultralytics import YOLO

                self._yolo = YOLO(str(yolo_path))
                self._loaded["yolo_seg_26"] = True
                self._errors.pop("yolo_seg_26", None)
            except Exception as exc:
                logger.warning("YOLO load failed from %s: %s", yolo_path, exc)
                self._loaded["yolo_seg_26"] = False
                self._errors["yolo_seg_26"] = str(exc)
        else:
            self._errors["yolo_seg_26"] = "weights file not found"

        if seg_path is not None:
            self._paths["segformer"] = str(seg_path)
            try:
                try:
                    from segmentation_service.runtime import SegmentationRuntime
                    from segmentation_service.settings import load_settings as load_seg_settings
                except ModuleNotFoundError:
                    from app.segmentation_service.runtime import SegmentationRuntime
                    from app.segmentation_service.settings import load_settings as load_seg_settings

                seg_settings = load_seg_settings()
                seg_settings.checkpoint_path = seg_path
                runtime = SegmentationRuntime(seg_settings)
                runtime.load()
                self._segformer = runtime
                self._loaded["segformer"] = True
                self._errors.pop("segformer", None)
            except Exception as exc:
                logger.warning("SegFormer load failed from %s: %s", seg_path, exc)
                self._loaded["segformer"] = False
                self._errors["segformer"] = str(exc)
        else:
            unpacked = ROOT / "config" / "segformer_best" / "best_iou"
            if unpacked.is_dir():
                self._errors["segformer"] = (
                    "weights file not found; unpacked checkpoint at "
                    "config/segformer_best/best_iou — run: python scripts/pack_segformer_weights.py"
                )
            else:
                self._errors["segformer"] = "weights file not found"
        return self.health()

    def health(self) -> dict[str, Any]:
        models = []
        for code in ("yolo_seg_26", "segformer"):
            models.append(
                {
                    "code": code,
                    "loaded": self._loaded[code],
                    "weights": self._paths.get(code),
                    "error": self._errors.get(code),
                }
            )
        status = "ready" if any(self._loaded.values()) else "unavailable"
        return {"status": status, "models": models}

    def infer(self, file_bytes: bytes, filename: str, request: InferenceRequest) -> InferenceResponse:
        image = _decode_image(file_bytes)
        if request.model == "yolo_seg_26":
            payload = self._run_yolo(image, request.confidence)
        elif request.model == "segformer":
            payload = self._run_segformer(image, request.confidence)
        else:
            raise ValueError(f"Unknown model {request.model}")
        return InferenceResponse(
            model=payload["model"],
            polygons=[InferenceFeature(**item) for item in payload.get("polygons", [])],
            points=[InferenceFeature(**item) for item in payload.get("points", [])],
        )

    def _run_yolo(self, image: np.ndarray, confidence: float) -> dict[str, Any]:
        if self._yolo is None:
            raise RuntimeError("YOLO weights are not loaded")
        results = self._yolo.predict(image, conf=confidence, verbose=False)
        polygons: list[dict[str, Any]] = []
        points: list[dict[str, Any]] = []
        class_map = {0: 2, 5: 5, 6: 6, 7: 4, 9: 3}
        for result in results:
            boxes = getattr(result, "boxes", None)
            masks = getattr(result, "masks", None)
            if masks is not None and getattr(masks, "xy", None):
                for idx, poly in enumerate(masks.xy):
                    cls = int(boxes.cls[idx]) if boxes is not None else 0
                    conf = float(boxes.conf[idx]) if boxes is not None else confidence
                    mapped = class_map.get(cls, 2)
                    if mapped in {5, 6}:
                        xs = poly[:, 0]
                        ys = poly[:, 1]
                        cx, cy = float(xs.mean()), float(ys.mean())
                        radius = float(max(xs.max() - xs.min(), ys.max() - ys.min()) / 2)
                        points.append(
                            {
                                "class_id": mapped,
                                "confidence": conf,
                                "geometry": {"type": "Point", "coordinates": [cx, cy]},
                                "radius_approx": radius,
                                "area_approx": float(np.pi * radius * radius),
                            }
                        )
                    else:
                        ring = [[float(x), float(y)] for x, y in poly]
                        if ring and ring[0] != ring[-1]:
                            ring.append(ring[0])
                        polygons.append(
                            {
                                "class_id": mapped,
                                "confidence": conf,
                                "geometry": {"type": "Polygon", "coordinates": [ring]},
                            }
                        )
            elif boxes is not None:
                for box in boxes:
                    cls = int(box.cls)
                    conf = float(box.conf)
                    mapped = class_map.get(cls, 5)
                    xyxy = box.xyxy[0].tolist()
                    cx = (xyxy[0] + xyxy[2]) / 2
                    cy = (xyxy[1] + xyxy[3]) / 2
                    points.append(
                        {
                            "class_id": mapped if mapped in {5, 6} else 5,
                            "confidence": conf,
                            "geometry": {
                                "type": "Point",
                                "coordinates": [float(cx), float(cy)],
                            },
                        }
                    )
        return {"model": "yolo_seg_26", "polygons": polygons, "points": points}

    def _run_segformer(self, image: np.ndarray, confidence: float) -> dict[str, Any]:
        if self._segformer is None:
            raise RuntimeError("SegFormer weights are not loaded")
        import cv2
        from segmentation_service.pipeline import run_segmentation
        from segmentation_service.schemas import SegmentRequest

        request = SegmentRequest(threshold=confidence, include_geojson=True)
        result = run_segmentation(self._segformer, image, None, request)
        polygons: list[dict[str, Any]] = []
        for item in result.polygons or []:
            coords = getattr(item, "coordinates", None) or []
            if len(coords) < 3:
                continue
            ring = [[float(p[0]), float(p[1])] for p in coords]
            ring.append(ring[0])
            polygons.append(
                {
                    "class_id": 2,
                    "confidence": float(getattr(item, "confidence", None) or confidence),
                    "geometry": {"type": "Polygon", "coordinates": [ring]},
                }
            )
        if not polygons and getattr(result, "mask_png_b64", None):
            import base64

            raw = base64.b64decode(result.mask_png_b64)
            mask = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
            if mask is not None:
                polygons.extend(_mask_to_polygons(mask, 2, confidence))
        return {"model": "segformer", "polygons": polygons, "points": []}


def _decode_image(data: bytes) -> np.ndarray:
    import cv2

    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError("Cannot decode image")
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
    elif img.shape[2] == 4:
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2RGB)
    else:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    return img


def _mask_to_polygons(mask: np.ndarray, class_id: int, confidence: float) -> list[dict[str, Any]]:
    import cv2

    mask_u8 = (mask > 0).astype(np.uint8)
    contours, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    features = []
    for contour in contours:
        if cv2.contourArea(contour) < 25:
            continue
        pts = contour.squeeze(1)
        if pts.ndim != 2 or len(pts) < 3:
            continue
        ring = [[float(x), float(y)] for x, y in pts]
        ring.append(ring[0])
        features.append(
            {
                "class_id": class_id,
                "confidence": confidence,
                "geometry": {"type": "Polygon", "coordinates": [ring]},
            }
        )
    return features


runtime = ModelRuntime()


def load_models() -> dict[str, Any]:
    return runtime.load_models()


def health() -> dict[str, Any]:
    return runtime.health()


def infer(file_bytes: bytes, filename: str, request: InferenceRequest) -> InferenceResponse:
    return runtime.infer(file_bytes, filename, request)


def infer_sync(file_bytes: bytes, filename: str, request: InferenceRequest) -> InferenceResponse:
    return infer(file_bytes, filename, request)
