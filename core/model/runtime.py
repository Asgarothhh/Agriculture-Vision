"""Загрузка чекпоинта и жизненный цикл модели на GPU/CPU."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import torch

from field_detecter.seg_infer import load_segformer_checkpoint
from field_detecter.train_seg import Segformer4ChWrapper
from model.settings import ModelSettings


class SegmentationRuntime:
    """
    Один экземпляр на процесс: модель грузится один раз, инференс под семафором.

    FP16: torch.autocast на CUDA (см. model.inference.predict_prob).
    """

    def __init__(self, settings: ModelSettings | None = None) -> None:
        from model.settings import load_settings

        self.settings = settings or load_settings()
        self._model: Segformer4ChWrapper | None = None
        self._meta: dict[str, Any] = {}
        self._device: torch.device | None = None
        self._lock = threading.Lock()
        self._infer_semaphore = threading.Semaphore(
            max(1, self.settings.max_concurrent_inferences)
        )

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def device(self) -> torch.device:
        if self._device is None:
            raise RuntimeError("Model not loaded; call load() first")
        return self._device

    @property
    def model(self) -> Segformer4ChWrapper:
        if self._model is None:
            raise RuntimeError("Model not loaded; call load() first")
        return self._model

    @property
    def meta(self) -> dict[str, Any]:
        return dict(self._meta)

    def load(self, checkpoint_path: str | Path | None = None) -> None:
        with self._lock:
            if self._model is not None:
                return
            path = Path(checkpoint_path or self.settings.checkpoint_path)
            if not path.is_file():
                raise FileNotFoundError(
                    f"Checkpoint not found: {path}. "
                    "Train the model or set MODEL_CHECKPOINT_PATH."
                )
            device_name = self.settings.resolve_device()
            self._device = torch.device(device_name)
            model, meta = load_segformer_checkpoint(path, device=self._device)
            model.eval()
            self._model = model
            ckpt_threshold = meta.get("threshold")
            if ckpt_threshold is not None:
                self._meta = {**meta, "checkpoint_threshold": ckpt_threshold}
            else:
                self._meta = meta
            self._meta["checkpoint_path"] = str(path.resolve())
            self._meta["fp16_active"] = self.settings.fp16_enabled(device_name)

    def unload(self) -> None:
        with self._lock:
            self._model = None
            self._meta = {}
            self._device = None
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    def acquire_inference_slot(self) -> threading.Semaphore:
        return self._infer_semaphore
