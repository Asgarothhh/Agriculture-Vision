"""
Движок инференса для YOLO (Ultralytics) — сегментация аграрных полей.
"""

from __future__ import annotations
import base64
import time
from pathlib import Path
import cv2
import numpy as np
from ultralytics import YOLO

from models.engines.base import BaseSegmentationEngine
from models.schemas import (
    SegmentRequest,
    YoloSegmentResponse,
    YoloDetectionPayload,
    SegmentMetrics,
)
from models.utils.visualize import draw_detections, encode_png


class YoloSegmentationEngine(BaseSegmentationEngine):
    """Реализация движка сегментации на базе архитектуры Ultralytics YOLO."""

    def load(self) -> None:
        weights_path = getattr(self.settings, "yolo_weights_path", "config/yolo_best.pt")
        if not Path(weights_path).exists():
            weights_path = getattr(self.settings, "yolo_fallback_weights", "yolo11m-seg.pt")

        self.model = YOLO(weights_path)
        self.meta["checkpoint_path"] = str(weights_path)
        # Загружаем имена классов из настроек, если они заданы
        self.labels = getattr(
            self.settings, "yolo_class_names",
            self.model.names if hasattr(self.model, "names") else {},
        )

        self.meta["val_metrics"] = getattr(self.settings, "cached_val_metrics", None)

    def unload(self) -> None:
        if self.model is not None:
            del self.model
            self.model = None
        if self.device.type == "cuda":
            import torch
            torch.cuda.empty_cache()

    def segment(self, rgb: np.ndarray, nir: np.ndarray | None, request: SegmentRequest) -> YoloSegmentResponse:
        if not self.is_loaded:
            raise RuntimeError("YOLO model is not loaded")

        h_orig, w_orig = rgb.shape[:2]
        conf_threshold = request.threshold or getattr(self.settings, "default_confidence_threshold", 0.4)
        iou_threshold = getattr(self.settings, "default_iou_threshold", 0.5)
        imgsz = getattr(self.settings, "inference_image_size", 640)

        start_time = time.perf_counter()
        outputs = self.model.predict(
            source=rgb,
            imgsz=imgsz,
            conf=conf_threshold,
            iou=iou_threshold,
            device=str(self.device),
            verbose=False,
            augment=bool(request.tta),
        )
        inference_ms = (time.perf_counter() - start_time) * 1000
        results = outputs[0]

        detections: list[YoloDetectionPayload] = []
        confidences: list[float] = []
        total_mask_pixels = np.zeros((h_orig, w_orig), dtype=np.uint8)

        if results.boxes is not None and len(results.boxes) > 0:
            boxes = results.boxes.cpu().numpy()
            masks_xy = results.masks.xy if results.masks is not None else []
            masks_data = results.masks.data.cpu().numpy() if results.masks is not None else None

            for idx, box in enumerate(boxes):
                class_id = int(box.cls[0])
                conf = float(box.conf[0])
                confidences.append(conf)

                xmin, ymin, xmax, ymax = box.xyxy[0]
                bbox = [int(xmin), int(ymin), int(xmax), int(ymax)]

                polygon_points: list[tuple[int, int]] = []
                area_px = 0.0
                if idx < len(masks_xy) and len(masks_xy[idx]) > 0:
                    polygon_points = [(int(x), int(y)) for x, y in masks_xy[idx]]
                    contour_array = np.array(polygon_points, dtype=np.int32)
                    area_px = float(cv2.contourArea(contour_array))

                # Агрегируем растровую маску для метрики покрытия
                if masks_data is not None:
                    raw_m = masks_data[idx]
                    resized_m = cv2.resize(raw_m, (w_orig, h_orig), interpolation=cv2.INTER_NEAREST)
                    total_mask_pixels = np.maximum(total_mask_pixels, (resized_m > 0.5).astype(np.uint8))

                detections.append(YoloDetectionPayload(
                    label=self.labels.get(class_id, f"class_{class_id}"),
                    confidence=conf,
                    polygon_px=polygon_points,
                    area_px=area_px,
                    bbox_xyxy=bbox,
                    valid=area_px > 0,
                ))

        # Расчёт метрик
        prob_mean = float(np.mean(confidences)) if confidences else 0.0
        prob_std = float(np.std(confidences)) if confidences else 0.0
        area_frac = float(cv2.countNonZero(total_mask_pixels)) / (h_orig * w_orig) if h_orig * w_orig > 0 else 0.0

        metrics = SegmentMetrics(
            threshold_used=conf_threshold,
            area_frac=area_frac,
            prob_mean=prob_mean,
            prob_std=prob_std,
            mode="tta" if request.tta else "sliding" if request.use_sliding else "standard",
            inference_ms=inference_ms,
            fp16=self.meta["fp16_active"],
            device=str(self.device),
        )

        mask_png_base64: str | None = None
        if request.include_mask_png and len(detections) > 0:
            _, buffer = cv2.imencode(".png", total_mask_pixels * 255)
            mask_png_base64 = base64.b64encode(buffer).decode("utf-8")

        overlay_png_base64: str | None = None
        if request.include_overlay and len(detections) > 0:
            # Конвертируем RGB → BGR для OpenCV
            image_bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            detections_dicts = [
                {
                    "polygon_px": d.polygon_px,
                    "bbox_xyxy": d.bbox_xyxy,
                    "label": d.label,
                    "confidence": d.confidence,
                }
                for d in detections
            ]
            overlay_bgr = draw_detections(image_bgr, detections_dicts)
            overlay_bytes = encode_png(overlay_bgr)
            overlay_png_base64 = base64.b64encode(overlay_bytes).decode("utf-8")

        return YoloSegmentResponse(
            ok=True,
            detections=detections,
            geojson=None,
            mask_png_base64=mask_png_base64,
            overlay_png_base64=overlay_png_base64,
            image_hw=(h_orig, w_orig),
            checkpoint=self.meta["checkpoint_path"],
            val_metrics=self.meta["val_metrics"],
            metrics=metrics,
        )
