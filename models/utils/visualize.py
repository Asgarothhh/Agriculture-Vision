"""
Утилиты для визуализации результатов сегментации.
Создаёт изображение с наложенными масками/полигонами на оригинал.
"""

from __future__ import annotations
import cv2
import numpy as np


# Цвета для разных классов (BGR)
CLASS_COLORS: dict[int, tuple[int, int, int]] = {
    0: (0, 0, 0),       # background — чёрный (не отображается)
    1: (0, 255, 0),     # field — зелёный
    2: (255, 255, 0),   # double_plant — голубой
    3: (0, 165, 255),   # drydown — оранжевый
    4: (0, 0, 255),     # endrow — красный
    5: (255, 0, 255),   # nutrient_deficiency — розовый
    6: (0, 255, 255),   # planter_skip — жёлтый
    7: (128, 128, 128), # storm_damage — серый
    8: (255, 128, 0),   # water — синий (BGR: 0,128,255 → сине-голубой)
    9: (128, 0, 255),   # waterway — фиолетовый
    10: (0, 128, 255),  # weed_cluster — синий
}


def draw_mask_overlay(
    image_bgr: np.ndarray,
    mask: np.ndarray,
    alpha: float = 0.5,
    color: tuple[int, int, int] = (0, 255, 0),
) -> np.ndarray:
    """
    Накладывает бинарную маску на изображение с полупрозрачностью.

    Parameters:
        image_bgr: Исходное изображение (BGR, H, W, 3).
        mask: Бинарная маска (H, W) — пиксели > 0 считаются маской.
        alpha: Прозрачность наложения (0.0–1.0).
        color: Цвет маски в BGR.

    Returns:
        Изображение с наложенной маской (BGR).
    """
    overlay = image_bgr.copy()
    mask_bool = (mask > 0).astype(np.uint8)
    colored_mask = np.zeros_like(image_bgr, dtype=np.uint8)
    colored_mask[mask_bool == 1] = color
    overlay = cv2.addWeighted(overlay, 1.0 - alpha, colored_mask, alpha, 0)
    return overlay


def draw_class_mask_overlay(
    image_bgr: np.ndarray,
    class_mask: np.ndarray,
    alpha: float = 0.5,
) -> np.ndarray:
    """
    Накладывает мультиклассовую маску на изображение.
    Каждый класс отображается своим цветом (см. CLASS_COLORS).

    Parameters:
        image_bgr: Исходное изображение (BGR, H, W, 3).
        class_mask: Маска классов (H, W) — каждый пиксель содержит ID класса.
        alpha: Прозрачность наложения.

    Returns:
        Изображение с наложенной цветной маской (BGR).
    """
    overlay = image_bgr.copy()
    colored = np.zeros_like(image_bgr, dtype=np.uint8)
    for class_id, color in CLASS_COLORS.items():
        mask_bool = (class_mask == class_id).astype(np.uint8)
        colored[mask_bool == 1] = color
    overlay = cv2.addWeighted(overlay, 1.0 - alpha, colored, alpha, 0)
    return overlay


def draw_polygons(
    image_bgr: np.ndarray,
    polygons: list[list[tuple[int, int]]],
    color: tuple[int, int, int] = (0, 255, 0),
    thickness: int = 3,
) -> np.ndarray:
    """
    Рисует полигоны (контуры) на изображении.

    Parameters:
        image_bgr: Изображение (BGR).
        polygons: Список полигонов, каждый полигон — список точек [(x,y), ...].
        color: Цвет контура в BGR.
        thickness: Толщина линии.

    Returns:
        Изображение с нарисованными полигонами.
    """
    result = image_bgr.copy()
    for polygon in polygons:
        if len(polygon) < 3:
            continue
        pts = np.array(polygon, dtype=np.int32).reshape((-1, 1, 2))
        cv2.polylines(result, [pts], isClosed=True, color=color, thickness=thickness)
    return result


def draw_detections(
    image_bgr: np.ndarray,
    detections: list[dict],
    labels: dict[int, str] | None = None,
) -> np.ndarray:
    """
    Рисует все детекции YOLO на изображении: маску, bounding box, label.

    Parameters:
        image_bgr: Исходное изображение (BGR).
        detections: Список словарей с ключами:
            - "polygon_px": list[tuple[int,int]]
            - "bbox_xyxy": list[int] [x1,y1,x2,y2]
            - "label": str
            - "confidence": float
        labels: Словарь class_id → имя (для подписи, необязательно).

    Returns:
        Изображение с визуализацией.
    """
    result = image_bgr.copy()
    for det in detections:
        polygon = det.get("polygon_px", [])
        bbox = det.get("bbox_xyxy", [])
        label = det.get("label", "unknown")
        conf = det.get("confidence", 0.0)

        # Заливка маски полупрозрачным цветом
        if len(polygon) >= 3:
            pts = np.array(polygon, dtype=np.int32).reshape((-1, 1, 2))
            overlay = result.copy()
            cv2.fillPoly(overlay, [pts], color=(0, 255, 0))
            result = cv2.addWeighted(result, 0.7, overlay, 0.3, 0)
            # Контур полигона
            cv2.polylines(result, [pts], isClosed=True, color=(0, 255, 0), thickness=2)

        # Bounding box
        if len(bbox) == 4:
            x1, y1, x2, y2 = bbox
            cv2.rectangle(result, (x1, y1), (x2, y2), color=(255, 0, 0), thickness=2)

        # Подпись
        text = f"{label} {conf:.2f}"
        if bbox:
            cv2.putText(
                result, text, (bbox[0], bbox[1] - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2,
            )

    return result


def encode_png(image_bgr: np.ndarray) -> bytes:
    """
    Кодирует BGR-изображение в PNG-байты.

    Parameters:
        image_bgr: Изображение (BGR, H, W, 3).

    Returns:
        Сырые байты PNG.
    """
    success, buffer = cv2.imencode(".png", image_bgr)
    if not success:
        raise RuntimeError("Не удалось закодировать изображение в PNG")
    return buffer.tobytes()
