from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

from app.core.config import get_settings
from app.ml_service.schemas import InferenceFeature, InferenceRequest, InferenceResponse

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]

# ObjectClass ids (app/core/seed.py). SegFormer outputs field outlines only.
FIELD_CLASS_ID = 2
# YOLO class names from config/data.yaml -> ObjectClass ids of the spec categories.
YOLO_NAME_TO_CLASS: dict[str, int] = {
    "double_plant": 21,
    "drydown": 22,
    "endrow": 23,
    "water": 4,
    "waterway": 24,
    "weed_cluster": 25,
    "planter_skip": 26,
    "nutrient_deficiency": 27,
    "storm_damage": 28,
}
POINT_CLASS_IDS = frozenset({5, 6, 26})


def yolo_class_id(names: Any, cls: int) -> int | None:
    """Spec class id for a YOLO class index, or None for classes the app does not know."""
    name = names.get(cls) if isinstance(names, dict) else (names[cls] if 0 <= cls < len(names) else None)
    if name is None:
        return None
    return YOLO_NAME_TO_CLASS.get(str(name).strip().lower())


def _point_from_outline(poly: np.ndarray, class_id: int, confidence: float) -> dict[str, Any]:
    xs = poly[:, 0]
    ys = poly[:, 1]
    radius = float(max(xs.max() - xs.min(), ys.max() - ys.min()) / 2)
    return {
        "class_id": class_id,
        "confidence": confidence,
        "geometry": {"type": "Point", "coordinates": [float(xs.mean()), float(ys.mean())]},
        "radius_approx": radius,
        "area_approx": float(np.pi * radius * radius),
    }


# Sliced YOLO inference: a large map snapshot is cut into overlapping tiles of the
# model's training size, so small objects are not lost by shrinking the whole image.
YOLO_DEFAULT_IMGSZ = 640
YOLO_SLICE_OVERLAP = 0.2
YOLO_SLICE_MIN_FACTOR = 1.5  # slice only images noticeably larger than one tile
YOLO_SLICE_BATCH = 8


def yolo_train_size(model: Any) -> int:
    """Training image size of an Ultralytics model (its default predict size)."""
    sources = [getattr(model, "overrides", None), getattr(getattr(model, "model", None), "args", None)]
    for src in sources:
        value = src.get("imgsz") if isinstance(src, dict) else getattr(src, "imgsz", None)
        if value:
            try:
                return int(max(value) if isinstance(value, (list, tuple)) else value)
            except (TypeError, ValueError):
                continue
    return YOLO_DEFAULT_IMGSZ


def tile_windows(height: int, width: int, tile: int, overlap: float = YOLO_SLICE_OVERLAP) -> list[tuple[int, int, int, int]]:
    """Overlapping (x0, y0, x1, y1) windows covering the whole image; the last ones touch the edges."""
    tile = max(32, int(tile))
    stride = max(1, int(round(tile * (1.0 - overlap))))

    def starts(size: int) -> list[int]:
        if size <= tile:
            return [0]
        values = list(range(0, size - tile, stride))
        values.append(size - tile)
        return sorted(set(values))

    return [
        (x, y, min(width, x + tile), min(height, y + tile))
        for y in starts(height)
        for x in starts(width)
    ]


def merge_sliced_detections(
    polygons: list[dict[str, Any]], points: list[dict[str, Any]], min_point_dist: float = 8.0
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Joins pieces of one object cut by tile borders and drops duplicates from overlaps."""
    from shapely.geometry import Polygon as ShapelyPolygon
    from shapely.ops import unary_union

    by_class: dict[int, list[tuple[Any, float]]] = {}
    order: list[int] = []
    for item in polygons:
        ring = item["geometry"]["coordinates"][0]
        try:
            shape = ShapelyPolygon(ring).buffer(0)
        except Exception:
            continue
        if shape.is_empty:
            continue
        cid = int(item["class_id"])
        if cid not in by_class:
            by_class[cid] = []
            order.append(cid)
        by_class[cid].append((shape, float(item["confidence"])))

    merged_polygons: list[dict[str, Any]] = []
    for cid in order:
        items = by_class[cid]
        union = unary_union([shape for shape, _ in items])
        parts = list(getattr(union, "geoms", [union]))
        for part in parts:
            if part.is_empty or part.geom_type != "Polygon":
                continue
            conf = max((c for shape, c in items if shape.intersects(part)), default=0.0)
            rings = [[[float(x), float(y)] for x, y in part.exterior.coords]]
            rings += [[[float(x), float(y)] for x, y in hole.coords] for hole in part.interiors]
            merged_polygons.append(
                {"class_id": cid, "confidence": conf, "geometry": {"type": "Polygon", "coordinates": rings}}
            )

    kept: list[dict[str, Any]] = []
    for item in sorted(points, key=lambda p: -float(p["confidence"])):
        x, y = item["geometry"]["coordinates"]
        radius = float(item.get("radius_approx") or 0.0)
        duplicate = False
        for other in kept:
            if other["class_id"] != item["class_id"]:
                continue
            ox, oy = other["geometry"]["coordinates"]
            limit = max(min_point_dist, radius, float(other.get("radius_approx") or 0.0))
            if (x - ox) ** 2 + (y - oy) ** 2 <= limit * limit:
                duplicate = True
                break
        if not duplicate:
            kept.append(item)
    return merged_polygons, kept


def parse_yolo_results(
    results: Any, names: Any, dx: float = 0.0, dy: float = 0.0
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """YOLO results → polygon/point features in image pixels (shifted by the tile offset)."""
    polygons: list[dict[str, Any]] = []
    points: list[dict[str, Any]] = []
    for result in results:
        boxes = getattr(result, "boxes", None)
        masks = getattr(result, "masks", None)
        result_names = getattr(result, "names", None) or names
        if masks is not None and getattr(masks, "xy", None) is not None and len(masks.xy):
            for idx, poly in enumerate(masks.xy):
                if boxes is None:
                    continue
                class_id = yolo_class_id(result_names, int(boxes.cls[idx]))
                if class_id is None or len(poly) < 3:
                    continue
                conf = float(boxes.conf[idx])
                shifted = np.asarray(poly, dtype=float) + np.array([dx, dy])
                if class_id in POINT_CLASS_IDS:
                    points.append(_point_from_outline(shifted, class_id, conf))
                else:
                    ring = [[float(x), float(y)] for x, y in shifted]
                    if ring[0] != ring[-1]:
                        ring.append(ring[0])
                    polygons.append(
                        {
                            "class_id": class_id,
                            "confidence": conf,
                            "geometry": {"type": "Polygon", "coordinates": [ring]},
                        }
                    )
        elif boxes is not None:
            for box in boxes:
                class_id = yolo_class_id(result_names, int(box.cls))
                if class_id is None:
                    continue
                x0, y0, x1, y1 = (float(v) for v in box.xyxy[0].tolist())
                x0, x1 = x0 + dx, x1 + dx
                y0, y1 = y0 + dy, y1 + dy
                if class_id in POINT_CLASS_IDS:
                    points.append(
                        {
                            "class_id": class_id,
                            "confidence": float(box.conf),
                            "geometry": {"type": "Point", "coordinates": [(x0 + x1) / 2, (y0 + y1) / 2]},
                        }
                    )
                else:
                    ring = [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]
                    polygons.append(
                        {
                            "class_id": class_id,
                            "confidence": float(box.conf),
                            "geometry": {"type": "Polygon", "coordinates": [ring]},
                        }
                    )
    return polygons, points


M_PER_DEG_LAT = 111_320.0
GEOGRAPHIC_CRS = {"EPSG:4326", "OGC:CRS84", "CRS:84", "WGS84"}


def pixel_size_m(transform: list[float] | None, crs: str | None, height: int | None) -> float | None:
    """Ground size of one pixel (metres) from a GDAL transform; None if unknown."""
    if not transform or len(transform) < 6:
        return None
    west, pw, _rx, north, _ry, ph = (float(v) for v in transform[:6])
    if not pw or not ph:
        return None
    if not crs or str(crs).upper() in GEOGRAPHIC_CRS:
        lat = north + ph * (height or 0) / 2.0
        mx = abs(pw) * M_PER_DEG_LAT * float(np.cos(np.radians(lat)))
        my = abs(ph) * M_PER_DEG_LAT
        value = (mx + my) / 2.0
    else:
        value = (abs(pw) + abs(ph)) / 2.0  # projected CRS: metres
    return value if 1e-4 < value < 1e4 else None


def count_windows(height: int, width: int, tile: int, stride: int) -> int:
    """Sliding windows needed to cover height×width (same rule as segmentation_service)."""

    def starts(size: int) -> int:
        if size <= tile:
            return 1
        return len(range(0, size - tile + 1, max(1, stride))) + (0 if (size - tile) % max(1, stride) == 0 else 1)

    return starts(height) * starts(width)


def choose_working_scale(
    height: int,
    width: int,
    src_m_per_px: float | None,
    *,
    target_m_per_px: float,
    tile: int,
    stride: int,
    max_windows: int,
    max_upscale: float = 2.0,
) -> tuple[float | None, int, int, int]:
    """Working ground resolution for a snapshot: as close to the training scale as the
    window budget allows. Returns (work_m_per_px, work_h, work_w, windows).
    Without a known source scale the image stays as it is."""
    if not src_m_per_px or src_m_per_px <= 0:
        return None, height, width, count_windows(height, width, tile, stride)
    work = max(target_m_per_px, src_m_per_px / max_upscale)
    for _ in range(200):
        factor = src_m_per_px / work
        wh = max(1, int(round(height * factor)))
        ww = max(1, int(round(width * factor)))
        windows = count_windows(wh, ww, tile, stride)
        if windows <= max(1, max_windows):
            return work, wh, ww, windows
        work *= 1.08
    return work, wh, ww, windows


def resize_to(image: np.ndarray, height: int, width: int) -> np.ndarray:
    import cv2

    h, w = image.shape[:2]
    if (h, w) == (height, width):
        return image
    interp = cv2.INTER_CUBIC if height * width > h * w else cv2.INTER_AREA
    return cv2.resize(image, (width, height), interpolation=interp)


def scale_features(features: list[dict[str, Any]], sx: float, sy: float) -> list[dict[str, Any]]:
    """Maps features from working pixels back to source pixels."""
    if sx == 1.0 and sy == 1.0:
        return features
    out = []
    for item in features:
        geom = item["geometry"]
        if geom["type"] == "Point":
            x, y = geom["coordinates"]
            coords: Any = [x * sx, y * sy]
        else:
            coords = [[[x * sx, y * sy] for x, y in ring] for ring in geom["coordinates"]]
        scaled = {**item, "geometry": {"type": geom["type"], "coordinates": coords}}
        k = (sx + sy) / 2.0
        if item.get("radius_approx") is not None:
            scaled["radius_approx"] = item["radius_approx"] * k
        if item.get("area_approx") is not None:
            scaled["area_approx"] = item["area_approx"] * sx * sy
        out.append(scaled)
    return out


def segformer_polygons(items: Any, confidence: float, sx: float = 1.0, sy: float = 1.0) -> list[dict[str, Any]]:
    """Convert segmentation_service PolygonItem outlines (with holes) to inference features."""
    polygons: list[dict[str, Any]] = []

    def closed(points: Any) -> list[list[float]]:
        ring = [[float(x) * sx, float(y) * sy] for x, y in points]
        if ring and ring[0] != ring[-1]:
            ring.append(ring[0])
        return ring

    for item in items or []:
        coords = getattr(item, "polygon_px", None) or []
        if len(coords) < 3 or getattr(item, "valid", True) is False:
            continue
        rings = [closed(coords)]
        rings += [closed(hole) for hole in (getattr(item, "holes_px", None) or []) if len(hole) >= 3]
        polygons.append(
            {
                "class_id": FIELD_CLASS_ID,
                "confidence": confidence,
                "geometry": {"type": "Polygon", "coordinates": rings},
            }
        )
    return polygons


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

    def infer(
        self, file_bytes: bytes, filename: str, request: InferenceRequest, on_progress=None
    ) -> InferenceResponse:
        image = _decode_image(file_bytes)
        if request.model == "yolo_seg_26":
            payload = self._run_yolo(image, request.confidence, request.m_per_px, on_progress)
        elif request.model == "segformer":
            payload = self._run_segformer(image, request.confidence, request.m_per_px, on_progress)
        else:
            raise ValueError(f"Unknown model {request.model}")
        return InferenceResponse(
            model=payload["model"],
            polygons=[InferenceFeature(**item) for item in payload.get("polygons", [])],
            points=[InferenceFeature(**item) for item in payload.get("points", [])],
            info=payload.get("info", {}),
        )

    def _run_yolo(
        self, image: np.ndarray, confidence: float, m_per_px: float | None = None, on_progress=None
    ) -> dict[str, Any]:
        if self._yolo is None:
            raise RuntimeError("YOLO weights are not loaded")
        import cv2

        settings = get_settings()
        names = getattr(self._yolo, "names", None) or {}
        tile = yolo_train_size(self._yolo)
        src_h, src_w = image.shape[:2]
        stride = max(1, int(round(tile * (1.0 - YOLO_SLICE_OVERLAP))))
        work_m, work_h, work_w, windows_planned = choose_working_scale(
            src_h,
            src_w,
            m_per_px,
            target_m_per_px=settings.yolo_target_m_per_px,
            tile=tile,
            stride=stride,
            max_windows=settings.yolo_max_windows,
        )
        # _decode_image yields RGB; Ultralytics treats numpy input as BGR.
        bgr = cv2.cvtColor(resize_to(image, work_h, work_w), cv2.COLOR_RGB2BGR)
        height, width = bgr.shape[:2]
        sx, sy = src_w / width, src_h / height
        info = {
            "src_m_per_px": m_per_px,
            "work_m_per_px": work_m,
            "target_m_per_px": settings.yolo_target_m_per_px,
            "work_size": [width, height],
            "windows": 1,
        }
        if max(height, width) <= tile * YOLO_SLICE_MIN_FACTOR:
            # Small snapshot: one pass, as before.
            results = self._yolo.predict(bgr, conf=confidence, verbose=False)
            polygons, points = parse_yolo_results(results, names)
            if on_progress:
                on_progress(1, 1)
            return {
                "model": "yolo_seg_26",
                "polygons": scale_features(polygons, sx, sy),
                "points": scale_features(points, sx, sy),
                "info": info,
            }

        windows = tile_windows(height, width, tile)
        info["windows"] = len(windows)
        logger.info(
            "YOLO sliced inference: %sx%s px (%.3f m/px, source %s) → %s tiles of %s px",
            width,
            height,
            work_m or 0.0,
            m_per_px,
            len(windows),
            tile,
        )
        polygons: list[dict[str, Any]] = []
        points: list[dict[str, Any]] = []
        for start_idx in range(0, len(windows), YOLO_SLICE_BATCH):
            batch = windows[start_idx : start_idx + YOLO_SLICE_BATCH]
            crops = [np.ascontiguousarray(bgr[y0:y1, x0:x1]) for x0, y0, x1, y1 in batch]
            results = self._yolo.predict(crops, conf=confidence, verbose=False, imgsz=tile)
            for (x0, y0, _x1, _y1), result in zip(batch, results):
                tile_polys, tile_points = parse_yolo_results([result], names, dx=x0, dy=y0)
                polygons.extend(tile_polys)
                points.extend(tile_points)
            if on_progress:
                on_progress(min(len(windows), start_idx + len(batch)), len(windows))
        polygons, points = merge_sliced_detections(polygons, points)
        return {
            "model": "yolo_seg_26",
            "polygons": scale_features(polygons, sx, sy),
            "points": scale_features(points, sx, sy),
            "info": info,
        }

    def _run_segformer(
        self, image: np.ndarray, confidence: float, m_per_px: float | None = None, on_progress=None
    ) -> dict[str, Any]:
        if self._segformer is None:
            raise RuntimeError("SegFormer weights are not loaded")
        import cv2

        try:
            from segmentation_service.pipeline import run_segmentation
            from segmentation_service.schemas import SegmentRequest
        except ModuleNotFoundError:
            from app.segmentation_service.pipeline import run_segmentation
            from app.segmentation_service.schemas import SegmentRequest

        settings = get_settings()
        seg_settings = getattr(self._segformer, "settings", None)
        meta = getattr(self._segformer, "meta", None) or {}
        tile = int(meta.get("tile_size", getattr(seg_settings, "tile_size", 512)) or 512)
        stride = int(getattr(seg_settings, "sliding_stride", 0) or max(1, int(tile * 0.75)))
        src_h, src_w = image.shape[:2]
        work_m, work_h, work_w, windows = choose_working_scale(
            src_h,
            src_w,
            m_per_px,
            target_m_per_px=settings.seg_target_m_per_px,
            tile=tile,
            stride=stride,
            max_windows=settings.seg_max_windows,
        )
        work = resize_to(image, work_h, work_w)
        logger.info(
            "SegFormer: %sx%s px (source %s m/px) → %sx%s px at %.3f m/px, %s windows of %s",
            src_w,
            src_h,
            m_per_px,
            work_w,
            work_h,
            work_m or 0.0,
            windows,
            tile,
        )
        request = SegmentRequest(threshold=confidence, include_mask_png=True)
        result = run_segmentation(self._segformer, rgb=work, request=request, on_progress=on_progress)
        # Working image (and anything the pipeline shrank further) → source pixels.
        out_h, out_w = result.image_hw
        sx = src_w / out_w if out_w else 1.0
        sy = src_h / out_h if out_h else 1.0
        polygons = segformer_polygons(result.polygons, confidence, sx, sy)
        if not polygons and result.mask_png_base64:
            import base64

            raw = base64.b64decode(result.mask_png_base64)
            mask = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
            if mask is not None:
                if mask.shape[:2] != (src_h, src_w):
                    mask = cv2.resize(mask, (src_w, src_h), interpolation=cv2.INTER_NEAREST)
                polygons.extend(_mask_to_polygons(mask, FIELD_CLASS_ID, confidence))
        info = {
            "src_m_per_px": m_per_px,
            "work_m_per_px": work_m,
            "target_m_per_px": settings.seg_target_m_per_px,
            "work_size": [work_w, work_h],
            "windows": windows,
        }
        return {"model": "segformer", "polygons": polygons, "points": [], "info": info}


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


def infer(file_bytes: bytes, filename: str, request: InferenceRequest, on_progress=None) -> InferenceResponse:
    return runtime.infer(file_bytes, filename, request, on_progress=on_progress)


def infer_sync(file_bytes: bytes, filename: str, request: InferenceRequest, on_progress=None) -> InferenceResponse:
    return infer(file_bytes, filename, request, on_progress=on_progress)
