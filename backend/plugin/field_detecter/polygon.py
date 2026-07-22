"""Из маски сегментации — полигон, по которому может ехать трактор."""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np
from shapely.geometry import Polygon
from shapely.validation import make_valid


def mask_to_navigable_polygon(
    mask: np.ndarray,
    *,
    headland_margin_px: int = 12,
    simplify_tolerance: float = 2.5,
    min_area_px: float = 500.0,
) -> dict[str, Any]:
    """
    Строит полигон проезжей зоны внутри поля.

    headland_margin_px — отступ от края поля (разворотная полоса / край).
    simplify_tolerance — Douglas–Peucker в пикселях.
    """
    binary = (mask > 0).astype(np.uint8)
    if headland_margin_px > 0:
        k = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (headland_margin_px * 2 + 1, headland_margin_px * 2 + 1),
        )
        binary = cv2.erode(binary, k, iterations=1)

    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return {"polygon_px": [], "area_px": 0.0, "valid": False}

    cnt = max(contours, key=cv2.contourArea)
    area = float(cv2.contourArea(cnt))
    if area < min_area_px:
        return {"polygon_px": [], "area_px": area, "valid": False}

    epsilon = max(simplify_tolerance, 0.5)
    approx = cv2.approxPolyDP(cnt, epsilon, closed=True)
    ring = [(int(p[0][0]), int(p[0][1])) for p in approx]

    poly = make_valid(Polygon(ring))
    if poly.is_empty or not poly.is_valid:
        poly = make_valid(Polygon(ring).buffer(0))

    if poly.geom_type == "MultiPolygon":
        poly = max(poly.geoms, key=lambda g: g.area)

    coords = list(poly.exterior.coords)[:-1]  # без дубля замыкающей точки
    return {
        "polygon_px": [(int(x), int(y)) for x, y in coords],
        "area_px": float(poly.area),
        "valid": len(coords) >= 3,
    }


def mask_to_polygons(
    mask: np.ndarray,
    *,
    simplify_tolerance: float = 2.0,
    min_area_px: float = 80.0,
    max_polygons: int = 200,
) -> list[dict[str, Any]]:
    """Все значимые контуры на маске (например, отдельные здания)."""
    binary = (mask > 0).astype(np.uint8)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    result: list[dict[str, Any]] = []
    for cnt in sorted(contours, key=cv2.contourArea, reverse=True):
        area = float(cv2.contourArea(cnt))
        if area < min_area_px:
            continue
        approx = cv2.approxPolyDP(cnt, max(simplify_tolerance, 0.5), closed=True)
        ring = [(int(p[0][0]), int(p[0][1])) for p in approx]
        if len(ring) < 3:
            continue
        poly = make_valid(Polygon(ring))
        if poly.geom_type == "MultiPolygon":
            poly = max(poly.geoms, key=lambda g: g.area)
        coords = list(poly.exterior.coords)[:-1]
        result.append(
            {
                "polygon_px": [(int(x), int(y)) for x, y in coords],
                "area_px": float(poly.area),
            }
        )
        if len(result) >= max_polygons:
            break
    return result


def polygon_to_geojson_feature(
    polygon_px: list[tuple[int, int]],
    *,
    origin_lat: float,
    origin_lon: float,
    m_per_px: float = 0.05,
) -> dict[str, Any]:
    """
    Грубая привязка: локальная метрическая сетка от origin (для демо, не RTK).
    m_per_px — метров на пиксель (зависит от высоты съёмки / GSD).
    """
    ring = []
    for x, y in polygon_px:
        east = x * m_per_px
        north = -y * m_per_px
        # приближение: lat/lon смещение в метрах (малые расстояния)
        dlat = north / 111_320.0
        dlon = east / (111_320.0 * np.cos(np.radians(origin_lat)))
        ring.append([origin_lon + dlon, origin_lat + dlat])
    if ring and ring[0] != ring[-1]:
        ring.append(ring[0])
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [ring]},
        "properties": {"role": "navigable_headland", "m_per_px": m_per_px},
    }
