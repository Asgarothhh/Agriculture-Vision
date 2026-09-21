"""Разделение маски пашни на отдельные поля.

SegFormer обучен на `boundaries/` Agriculture-Vision — это контур сельхозземли
целиком, поэтому на сплошной пашне он отдаёт одну область на весь кадр.
Здесь эта область делится на участки по разделителям, которые видны на снимке:
дороги, лесополосы, межи и резкие переходы тона между полями.
"""

from __future__ import annotations

import cv2
import numpy as np


def _ellipse(radius_px: int) -> np.ndarray:
    r = max(int(radius_px), 1)
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (r * 2 + 1, r * 2 + 1))


def boundary_strength(rgb: np.ndarray, *, sigma: float = 2.0) -> np.ndarray:
    """Карта «похоже на разделитель полей» [0,1] из RGB."""
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    # bilateral сохраняет межи, но гасит внутреннюю текстуру (борозды, тень)
    gray = cv2.bilateralFilter(gray, 9, 60, 60)
    gx = cv2.Scharr(gray, cv2.CV_32F, 1, 0)
    gy = cv2.Scharr(gray, cv2.CV_32F, 0, 1)
    grad = cv2.magnitude(gx, gy)
    if sigma > 0:
        grad = cv2.GaussianBlur(grad, (0, 0), sigma)
    hi = float(np.quantile(grad, 0.995)) + 1e-6
    return np.clip(grad / hi, 0.0, 1.0)


def split_field_mask(
    mask: np.ndarray,
    rgb: np.ndarray,
    *,
    min_area_px: float = 4000.0,
    ridge_quantile: float = 0.80,
    boundary_sigma: float = 2.0,
    marker_open_px: int = 3,
) -> tuple[np.ndarray, int]:
    """
    Маска пашни → карта участков (0 = фон, 1..n = отдельные поля).

    ridge_quantile — доля «спокойных» пикселей поля: выше квантиля градиент
    считается разделителем. Меньше значение → дробление на больше участков.
    """
    field = (mask > 0).astype(np.uint8)
    if not field.any():
        return np.zeros(field.shape, np.int32), 0

    strength = boundary_strength(rgb, sigma=boundary_sigma)
    inside = strength[field > 0]
    ridge_th = float(np.quantile(inside, np.clip(ridge_quantile, 0.05, 0.99)))

    interior = field.copy()
    interior[strength > ridge_th] = 0
    if marker_open_px > 0:
        interior = cv2.morphologyEx(interior, cv2.MORPH_OPEN, _ellipse(marker_open_px))

    n, labels, stats, _ = cv2.connectedComponentsWithStats(interior, connectivity=8)
    markers = np.zeros(field.shape, np.int32)
    next_id = 0
    for i in range(1, n):
        if float(stats[i, cv2.CC_STAT_AREA]) < min_area_px:
            continue
        next_id += 1
        markers[labels == i] = next_id

    if next_id == 0:
        # разделителей не нашлось — поле цельное
        markers[field > 0] = 1
        next_id = 1

    background_id = next_id + 1
    markers[field == 0] = background_id

    relief = cv2.cvtColor((strength * 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    cv2.watershed(relief, markers)

    parcels = np.where((markers >= 1) & (markers <= next_id) & (field > 0), markers, 0)
    return parcels.astype(np.int32), next_id


def parcel_masks(
    parcels: np.ndarray,
    count: int,
    *,
    min_area_px: float = 4000.0,
    close_px: int = 5,
) -> list[np.ndarray]:
    """Карта участков → отдельные бинарные маски, крупные первыми."""
    out: list[tuple[float, np.ndarray]] = []
    for i in range(1, count + 1):
        m = (parcels == i).astype(np.uint8)
        area = float(m.sum())
        if area < min_area_px:
            continue
        if close_px > 0:
            # watershed оставляет линию -1 по границе: закрываем щель
            m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, _ellipse(close_px))
        out.append((area, m))
    out.sort(key=lambda t: t[0], reverse=True)
    return [m for _, m in out]
