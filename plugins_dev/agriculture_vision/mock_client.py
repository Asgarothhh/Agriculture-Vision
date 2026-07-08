"""Заглушки API — те же контракты, что в web/backend (когда сервер недоступен)."""

from __future__ import annotations

import base64
import random
import time
from typing import Any

from .constants import CROP_CLASSES, DEFAULT_SEGMENTATION_THRESHOLD


class MockAgricultureVisionClient:
    """Имитирует ответы FastAPI для разработки UI без запущенного backend."""

    def __init__(self, base_url: str = "mock://local", timeout: float = 120.0):
        self.base_url = base_url
        self.timeout = timeout

    def check_connection(self) -> dict[str, Any]:
        return {
            "message": "Agriculture Vision API (mock)",
            "version": "1.1.0-mock",
            "mode": "mock",
        }

    def health_segmentation(self, architecture: str = "all") -> dict[str, Any]:
        return {
            "status": "healthy",
            "model_loaded": True,
            "device": "cpu",
            "available_models": ["yolo", "segformer"],
            "mode": "mock",
        }

    def health_classification(self) -> dict[str, Any]:
        return {
            "status": "degraded",
            "classifier_loaded": False,
            "num_crop_classes": len(CROP_CLASSES),
            "mode": "mock",
        }

    def list_models(self) -> dict[str, Any]:
        return {
            "available_models": ["yolo", "segformer"],
            "mode": "mock",
        }

    def segment(
        self,
        image_bytes: bytes,
        architecture: str = "yolo",
        threshold: float | None = None,
        tta: bool = False,
        include_geojson: bool = False,
    ) -> dict[str, Any]:
        threshold = threshold or DEFAULT_SEGMENTATION_THRESHOLD
        time.sleep(0.3)

        # Примерные размеры из PNG-заголовка или дефолт
        h, w = 512, 512
        if len(image_bytes) > 24 and image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
            w = int.from_bytes(image_bytes[16:20], "big")
            h = int.from_bytes(image_bytes[20:24], "big")

        inference_ms = random.uniform(150, 400)
        metrics = {
            "threshold_used": threshold,
            "area_frac": 0.35,
            "prob_mean": 0.72,
            "prob_std": 0.08,
            "mode": "tta" if tta else "standard",
            "inference_ms": inference_ms,
            "fp16": False,
            "device": "cpu",
        }

        if architecture == "segformer":
            margin_x = int(w * 0.15)
            margin_y = int(h * 0.15)
            polygon = [
                (margin_x, margin_y),
                (w - margin_x, margin_y),
                (w - margin_x, h - margin_y),
                (margin_x, h - margin_y),
            ]
            return {
                "ok": True,
                "navigable": {
                    "polygon_px": polygon,
                    "area_px": float((w - 2 * margin_x) * (h - 2 * margin_y)),
                    "valid": True,
                },
                "image_hw": [h, w],
                "checkpoint": "mock/segformer_best.pt",
                "metrics": metrics,
                "mode": "mock",
            }

        cx, cy = w // 2, h // 2
        detections = [
            {
                "label": "field",
                "confidence": 0.91,
                "polygon_px": [
                    (int(w * 0.1), int(h * 0.1)),
                    (int(w * 0.9), int(h * 0.1)),
                    (int(w * 0.9), int(h * 0.9)),
                    (int(w * 0.1), int(h * 0.9)),
                ],
                "area_px": float(w * h * 0.64),
                "bbox_xyxy": [int(w * 0.1), int(h * 0.1), int(w * 0.9), int(h * 0.9)],
                "valid": True,
            },
            {
                "label": "water",
                "confidence": 0.78,
                "polygon_px": [
                    (cx - 40, cy - 30),
                    (cx + 40, cy - 30),
                    (cx + 40, cy + 30),
                    (cx - 40, cy + 30),
                ],
                "area_px": 4800.0,
                "bbox_xyxy": [cx - 40, cy - 30, cx + 40, cy + 30],
                "valid": True,
            },
            {
                "label": "weed_cluster",
                "confidence": 0.55,
                "polygon_px": [
                    (int(w * 0.7), int(h * 0.2)),
                    (int(w * 0.85), int(h * 0.2)),
                    (int(w * 0.85), int(h * 0.35)),
                    (int(w * 0.7), int(h * 0.35)),
                ],
                "area_px": 3600.0,
                "bbox_xyxy": [int(w * 0.7), int(h * 0.2), int(w * 0.85), int(h * 0.35)],
                "valid": True,
            },
        ]
        return {
            "ok": True,
            "detections": detections,
            "image_hw": [h, w],
            "checkpoint": "mock/yolo_best.pt",
            "metrics": metrics,
            "mode": "mock",
        }

    def classify_crop(
        self,
        image_base64: str,
        threshold: float | None = None,
    ) -> dict[str, Any]:
        threshold = threshold or 0.6
        probs = [random.random() for _ in CROP_CLASSES]
        total = sum(probs)
        probs = [p / total for p in probs]
        max_idx = max(range(len(probs)), key=lambda i: probs[i])
        predicted = CROP_CLASSES[max_idx]
        confidence = probs[max_idx]

        return {
            "ok": True,
            "predicted_class": predicted,
            "confidence": round(confidence, 4),
            "probabilities": [
                {"crop_class": cls, "probability": round(p, 4)}
                for cls, p in zip(CROP_CLASSES, probs)
            ],
            "requires_review": confidence < threshold,
            "threshold_used": threshold,
            "mode": "mock",
        }
