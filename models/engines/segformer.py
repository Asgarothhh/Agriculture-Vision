"""
Движок инференса для SegFormer — сегментация аграрных полей.
Поддерживает загрузку дообученного чекпоинта из config/.
"""

from __future__ import annotations
import base64
import time
from pathlib import Path
import cv2
import numpy as np
import torch
import torch.nn as nn
from transformers import SegformerImageProcessor, SegformerForSemanticSegmentation

from models.engines.base import BaseSegmentationEngine
from models.schemas import SegmentRequest, SegmentResponse, PolygonPayload, SegmentMetrics
from models.utils.visualize import draw_mask_overlay, encode_png


class SegFormerSegmentationEngine(BaseSegmentationEngine):
    """Движок инференса для моделей семейства SegFormer."""

    def load(self) -> None:
        """
        Загружает модель SegFormer.
        Если локальный чекпоинт (segformer_weights_path) существует —
        загружаем его поверх архитектуры pretrained-модели.
        Иначе используем pretrained-модель как есть (без дообучения).
        """
        pretrained = getattr(
            self.settings, "segformer_pretrained_model",
            "nvidia/segformer-b5-finetuned-ade-640-640",
        )
        local_checkpoint = getattr(self.settings, "segformer_weights_path", "config/segformer_best.pt")
        num_labels = getattr(self.settings, "segformer_num_labels", 10)

        # Загружаем процессор (feature extractor)
        self.processor = SegformerImageProcessor.from_pretrained(pretrained)

        if Path(local_checkpoint).exists():
            # Загружаем архитектуру с правильным количеством классов,
            # затем подменяем веса из локального чекпоинта
            self.model = SegformerForSemanticSegmentation.from_pretrained(
                pretrained,
                num_labels=num_labels,
                ignore_mismatched_sizes=True,
            )
            state_dict = torch.load(local_checkpoint, map_location=self.device)
            # Если чекпоинт содержит полный state_dict модели, а не только веса
            if "state_dict" in state_dict:
                state_dict = state_dict["state_dict"]
            # Убираем префикс "model." если он есть (из DDP/Lightning)
            state_dict = {k.removeprefix("model."): v for k, v in state_dict.items()}
            self.model.load_state_dict(state_dict, strict=False)
            self.meta["checkpoint_path"] = str(local_checkpoint)
        else:
            # Pretrained-модель (без дообучения)
            self.model = SegformerForSemanticSegmentation.from_pretrained(pretrained)
            self.meta["checkpoint_path"] = pretrained

        self.model.to(self.device)
        self.model.eval()

        # Загружаем имена классов из настроек
        self.labels = getattr(self.settings, "segformer_class_names", {})
        self.meta["val_metrics"] = getattr(self.settings, "cached_val_metrics", None)

    def unload(self) -> None:
        if self.model is not None:
            del self.model
            del self.processor
            self.model = None
            self.processor = None
        if self.device.type == "cuda":
            torch.cuda.empty_cache()

    def segment(self, rgb: np.ndarray, nir: np.ndarray | None, request: SegmentRequest) -> SegmentResponse:
        if not self.is_loaded:
            raise RuntimeError("SegFormer model is not loaded")

        h_orig, w_orig = rgb.shape[:2]
        threshold = request.threshold or getattr(self.settings, "default_confidence_threshold", 0.5)

        start_time = time.perf_counter()
        inputs = self.processor(images=rgb, return_tensors="pt").to(self.device)

        with torch.no_grad():
            outputs = self.model(**inputs)
            logits = outputs.logits

        upsampled_logits = nn.functional.interpolate(
            logits,
            size=(h_orig, w_orig),
            mode="bilinear",
            align_corners=False,
        )

        probabilities = torch.softmax(upsampled_logits, dim=1)[0]
        pred_seg = upsampled_logits.argmax(dim=1)[0].cpu().numpy().astype(np.uint8)
        inference_ms = (time.perf_counter() - start_time) * 1000

        # Бинарная маска "navigable" — класс 1 (field) для совместимости
        # В новой модели можно выделять все классы 1..N (кроме фона 0)
        navigable_mask = (pred_seg > 0).astype(np.uint8) * 255

        # Извлекаем полигоны (внешние контуры)
        contours, _ = cv2.findContours(navigable_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        polygon_points: list[tuple[int, int]] = []
        area_px = 0.0

        if contours:
            largest_contour = max(contours, key=cv2.contourArea)
            area_px = float(cv2.contourArea(largest_contour))
            polygon_points = [(int(pt[0][0]), int(pt[0][1])) for pt in largest_contour]

        # Вероятностные метрики
        prob_mean = 0.0
        prob_std = 0.0
        if np.any(pred_seg > 0):
            # Берём максимум вероятности по всем не-фоновым классам
            prob_mask, _ = probabilities[1:].max(dim=0)
            prob_mask_np = prob_mask.cpu().numpy()
            prob_mean = float(np.mean(prob_mask_np[pred_seg > 0]))
            prob_std = float(np.std(prob_mask_np[pred_seg > 0]))

        area_frac = float(cv2.countNonZero(navigable_mask)) / (h_orig * w_orig) if h_orig * w_orig > 0 else 0.0

        metrics = SegmentMetrics(
            threshold_used=threshold,
            area_frac=area_frac,
            prob_mean=prob_mean,
            prob_std=prob_std,
            mode="standard",
            inference_ms=inference_ms,
            fp16=self.meta["fp16_active"],
            device=str(self.device),
        )

        mask_png_base64: str | None = None
        if request.include_mask_png:
            _, buffer = cv2.imencode(".png", navigable_mask)
            mask_png_base64 = base64.b64encode(buffer).decode("utf-8")

        overlay_png_base64: str | None = None
        if request.include_overlay:
            # Конвертируем RGB → BGR
            image_bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            overlay_bgr = draw_mask_overlay(
                image_bgr, navigable_mask,
                alpha=0.5, color=(0, 255, 0),
            )
            # Дорисовываем контур полигона
            if polygon_points:
                pts = np.array(polygon_points, dtype=np.int32).reshape((-1, 1, 2))
                cv2.polylines(overlay_bgr, [pts], isClosed=True, color=(0, 255, 0), thickness=3)
            overlay_bytes = encode_png(overlay_bgr)
            overlay_png_base64 = base64.b64encode(overlay_bytes).decode("utf-8")

        return SegmentResponse(
            ok=True,
            navigable=PolygonPayload(
                polygon_px=polygon_points,
                area_px=area_px,
                valid=area_px > 0,
            ),
            geojson=None,
            mask_png_base64=mask_png_base64,
            overlay_png_base64=overlay_png_base64,
            image_hw=(h_orig, w_orig),
            checkpoint=self.meta["checkpoint_path"],
            val_metrics=self.meta["val_metrics"],
            metrics=metrics,
        )
