"""
Утилиты для чтения изображений из различных источников.
"""

from __future__ import annotations
from io import BytesIO
import cv2
import numpy as np


def read_image(file: BytesIO) -> np.ndarray:
    """
    Читает изображение из объекта BytesIO и возвращает его в формате
    numpy.ndarray (BGR, как загружает OpenCV).

    Parameters:
        file: Объект BytesIO, содержащий изображение.

    Returns:
        Изображение в формате BGR (H, W, 3).

    Raises:
        ValueError: Если изображение повреждено или формат не поддерживается.
    """
    nparr = np.frombuffer(file.getvalue(), np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    if img is None:
        raise ValueError(
            "Не удалось декодировать изображение. "
            "Файл поврежден или имеет неподдерживаемый формат."
        )

    return img


def read_image_rgb(file: BytesIO) -> np.ndarray:
    """
    Читает изображение и возвращает в RGB-формате (H, W, 3).

    Parameters:
        file: Объект BytesIO, содержащий изображение.

    Returns:
        Изображение в формате RGB (H, W, 3).
    """
    bgr = read_image(file)
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def read_image_bytes(file: BytesIO) -> bytes:
    """
    Возвращает сырые байты изображения из BytesIO.

    Parameters:
        file: Объект BytesIO, содержащий изображение.

    Returns:
        Сырые байты изображения.
    """
    return file.getvalue()
