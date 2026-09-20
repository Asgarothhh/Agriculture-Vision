"""
Оркестратор контекста выполнения моделей.
Управляет жизненным циклом YOLO и SegFormer движков.
"""

from __future__ import annotations
from threading import Semaphore
import numpy as np
from models.settings import Settings
from models.engines.base import BaseSegmentationEngine
from models.engines.yolo import YoloSegmentationEngine
from models.engines.segformer import SegFormerSegmentationEngine
from models.schemas import SegmentRequest, SegmentResponse, YoloSegmentResponse


class SegmentationRuntime:
    """Оркестратор контекста выполнения моделей."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.architecture_type: str = getattr(settings, "model_architecture", "yolo").lower()

        if self.architecture_type == "yolo":
            self.engine: BaseSegmentationEngine = YoloSegmentationEngine(settings)
        elif self.architecture_type == "segformer":
            self.engine: BaseSegmentationEngine = SegFormerSegmentationEngine(settings)
        else:
            raise ValueError(f"Unsupported architecture type: {self.architecture_type}")

        self._semaphore = Semaphore(settings.max_concurrent_inferences)

    def load(self) -> None:
        """Загружает модель в память."""
        self.engine.load()

    def unload(self) -> None:
        """Выгружает модель из памяти."""
        self.engine.unload()

    @property
    def is_loaded(self) -> bool:
        """Проверка, загружена ли модель."""
        return self.engine.is_loaded

    @property
    def device(self) -> str:
        """Устройство, на котором выполняется модель (cpu/cuda)."""
        return str(self.engine.device)

    @property
    def meta(self) -> dict:
        """Метаданные модели (путь к чекпоинту, метрики и т.д.)."""
        return self.engine.meta

    def acquire_inference_slot(self) -> Semaphore:
        """Возвращает семафор для ограничения конкурентных инференсов."""
        return self._semaphore

    def run_segmentation(
        self,
        rgb: np.ndarray,
        request: SegmentRequest,
    ) -> SegmentResponse | YoloSegmentResponse:
        """
        Выполняет сегментацию изображения.

        Args:
            rgb: RGB-изображение (H, W, 3).
            request: Параметры запроса.

        Returns:
            Ответ с результатами сегментации.
        """
        # Захват слота инференса
        with self._semaphore:
            return self.engine.segment(rgb, request)
