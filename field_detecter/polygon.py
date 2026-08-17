"""Из маски сегментации — полигон, по которому может ехать трактор."""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.validation import make_valid


def _largest_polygon(geom: BaseGeometry) -> Polygon | None:
    """Достаёт самый большой Polygon из результата make_valid (может быть
    Polygon / MultiPolygon / GeometryCollection с точками и линиями)."""
    if geom is None or geom.is_empty:
        return None
    if geom.geom_type == "Polygon":
        return geom
    if geom.geom_type in ("MultiPolygon", "GeometryCollection"):
        polys = [g for g in geom.geoms if g.geom_type == "Polygon" and not g.is_empty]
        if not polys:
            return None
        return max(polys, key=lambda g: g.area)
    return None


def _ellipse_kernel(radius_px: int) -> np.ndarray:
    return cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (radius_px * 2 + 1, radius_px * 2 + 1)
    )


def smooth_binary_mask(
    binary: np.ndarray,
    *,
    open_px: int = 0,
    close_px: int = 0,
    blur_px: int = 0,
) -> np.ndarray:
    """Убирает пиксельный шум маски: крошку (open), зазубрины и дырки (close),
    затем скругляет край размытием — иначе контур получается рваным."""
    out = (binary > 0).astype(np.uint8)
    if open_px > 0:
        out = cv2.morphologyEx(out, cv2.MORPH_OPEN, _ellipse_kernel(int(open_px)))
    if close_px > 0:
        out = cv2.morphologyEx(out, cv2.MORPH_CLOSE, _ellipse_kernel(int(close_px)))
    if blur_px > 0:
        ksize = int(blur_px) * 2 + 1
        blurred = cv2.GaussianBlur(out * 255, (ksize, ksize), 0)
        out = (blurred > 127).astype(np.uint8)
    return out


def _smooth_polygon(poly: Polygon, radius: float) -> Polygon:
    """Векторное скругление: closing убирает вмятины, opening срезает выступы.
    Если операция съедает фигуру (узкое поле), возвращаем предыдущий вариант."""
    if radius <= 0:
        return poly
    closed = _largest_polygon(
        make_valid(poly.buffer(radius, join_style=1).buffer(-radius, join_style=1))
    )
    if closed is None or closed.area < poly.area * 0.5:
        return poly
    opened = _largest_polygon(
        make_valid(closed.buffer(-radius, join_style=1).buffer(radius, join_style=1))
    )
    if opened is None or opened.area < closed.area * 0.5:
        return closed
    return opened


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

    poly = _largest_polygon(make_valid(Polygon(ring)))
    if poly is None:
        poly = _largest_polygon(make_valid(Polygon(ring).buffer(0)))
    if poly is None:
        return {"polygon_px": [], "area_px": area, "valid": False}

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
    open_px: int = 0,
    close_px: int = 0,
    blur_px: int = 0,
    smooth_px: float = 0.0,
) -> list[dict[str, Any]]:
    """Все значимые контуры на маске (например, границы отдельных полей)."""
    binary = smooth_binary_mask(
        mask, open_px=open_px, close_px=close_px, blur_px=blur_px
    )
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
        poly = _largest_polygon(make_valid(Polygon(ring)))
        if poly is None:
            poly = _largest_polygon(make_valid(Polygon(ring).buffer(0)))
        if poly is None:
            continue
        poly = _smooth_polygon(poly, smooth_px)
        if simplify_tolerance > 0:
            simplified = _largest_polygon(
                make_valid(poly.simplify(simplify_tolerance, preserve_topology=True))
            )
            if simplified is not None and not simplified.is_empty:
                poly = simplified
        if poly.area < min_area_px:
            continue
        coords = list(poly.exterior.coords)[:-1]
        if len(coords) < 3:
            continue
        result.append(
            {
                "polygon_px": [(int(round(x)), int(round(y))) for x, y in coords],
                "area_px": float(poly.area),
            }
        )
        if len(result) >= max_polygons:
            break
    return result


def mask_to_field_polygons(
    mask: np.ndarray,
    rgb: np.ndarray | None = None,
    *,
    split_parcels: bool = True,
    ridge_quantile: float = 0.80,
    boundary_sigma: float = 2.0,
    simplify_tolerance: float = 6.0,
    min_area_px: float = 4000.0,
    max_polygons: int = 200,
    open_px: int = 0,
    close_px: int = 0,
    blur_px: int = 0,
    smooth_px: float = 0.0,
) -> list[dict[str, Any]]:
    """Границы отдельных полей: маска пашни делится на участки, затем контуры."""
    binary = smooth_binary_mask(
        mask, open_px=open_px, close_px=close_px, blur_px=blur_px
    )
    if not split_parcels or rgb is None or not binary.any():
        return mask_to_polygons(
            binary,
            simplify_tolerance=simplify_tolerance,
            min_area_px=min_area_px,
            max_polygons=max_polygons,
            smooth_px=smooth_px,
        )

    from field_detecter.parcels import parcel_masks, split_field_mask

    parcels, count = split_field_mask(
        binary,
        rgb,
        min_area_px=min_area_px,
        ridge_quantile=ridge_quantile,
        boundary_sigma=boundary_sigma,
    )
    result: list[dict[str, Any]] = []
    for pm in parcel_masks(parcels, count, min_area_px=min_area_px):
        polys = mask_to_polygons(
            pm,
            simplify_tolerance=simplify_tolerance,
            min_area_px=min_area_px,
            max_polygons=1,
            smooth_px=smooth_px,
        )
        result.extend(polys)
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
