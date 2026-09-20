from __future__ import annotations
from abc import ABC, abstractmethod
import numpy as np
import torch
from models.schemas import SegmentRequest, SegmentResponse, YoloSegmentResponse
from models.settings import Settings


class BaseSegmentationEngine(ABC):
    """
    Абстрактный базовый класс (интерфейс) для движков сегментации.
    Оркестрирует жизненный цикл конкретной архитектуры модели (YOLO, SegFormer и др.).
    """

    def __init__(self, settings: Settings) -> None:
        """
        Инициализация базовых параметров движка.
        
        Parameters:
            settings: Объект конфигурации приложения.
        """
        self.settings = settings
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = None
        self.labels: dict[int, str] = {}
        self.meta: dict[str, any] = {
            "fp16_active": self.device.type == "cuda",
            "checkpoint_path": None,
            "val_metrics": None
        }

    @property
    def is_loaded(self) -> bool:
        """Проверка, загружена ли модель в память."""
        return self.model is not None
    
    @abstractmethod
    def load(self) -> None:
        """Метод для загрузки архитектуры и весов модели."""
        pass

    @abstractmethod
    def unload(self) -> None:
        """Метод для освобождения ресурсов и выгрузки модели из GPU/RAM."""
        pass

    @abstractmethod
    def segment(self, rgb: np.ndarray | None, request: SegmentRequest) -> SegmentResponse | YoloSegmentResponse:
        """
        Выполняет полный цикл предобработки, инференса и постабработки.

        Parameters:
            rgb: Массив изображения в формате RGB (H, W, 3).
            nir: Необязательный массив ближнего инфракрасного диапазона (H, W).
            request: Спецификация параметров запроса (threshold, tta, и т.д.).

        Returns:
            SegmentResponse: Валидированный Pydantic-ответ для API.
        """
        pass
