"""Утилиты для работы с растровыми и векторными слоями QGIS."""

from __future__ import annotations
import base64
import struct
import zlib
from typing import Any

from qgis.core import (
    Qgis,
    QgsFeature,
    QgsFields,
    QgsField,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsRasterLayer,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QImage, QColor


def list_raster_layers() -> list[QgsRasterLayer]:
    layers = []
    for layer in QgsProject.instance().mapLayers().values():
        if isinstance(layer, QgsRasterLayer) and layer.isValid():
            layers.append(layer)
    return layers


def list_polygon_layers() -> list[QgsVectorLayer]:
    layers = []
    for layer in QgsProject.instance().mapLayers().values():
        if (
            isinstance(layer, QgsVectorLayer)
            and layer.isValid()
            and QgsWkbTypes.geometryType(layer.wkbType()) == Qgis.GeometryType.Polygon
        ):
            layers.append(layer)
    return layers


def _pixel_to_map(layer: QgsRasterLayer, x: float, y: float) -> QgsPointXY:
    extent = layer.extent()
    w = layer.width()
    h = layer.height()
    if w <= 0 or h <= 0:
        return QgsPointXY(extent.center())

    map_x = extent.xMinimum() + (x / w) * extent.width()
    map_y = extent.yMaximum() - (y / h) * extent.height()
    return QgsPointXY(map_x, map_y)


def polygon_px_to_geometry(
    polygon_px: list[tuple[int, int] | list[int]],
    layer: QgsRasterLayer,
) -> QgsGeometry | None:
    if not polygon_px or len(polygon_px) < 3:
        return None

    points = []
    for pt in polygon_px:
        x, y = int(pt[0]), int(pt[1])
        points.append(_pixel_to_map(layer, x, y))

    if points[0] != points[-1]:
        points.append(points[0])

    return QgsGeometry.fromPolygonXY([points])


def raster_layer_to_png_bytes(layer: QgsRasterLayer, max_size: int = 2048) -> bytes:
    """Экспорт растра в PNG для отправки в API или локальной обработки."""
    provider = layer.dataProvider()
    src_w = layer.width()
    src_h = layer.height()
    extent = layer.extent()

    scale = min(1.0, max_size / max(src_w, src_h))
    w = max(1, int(src_w * scale))
    h = max(1, int(src_h * scale))

    band_count = min(3, provider.bandCount())
    if band_count == 0:
        raise ValueError("Растровый слой не содержит каналов")

    image = QImage(w, h, QImage.Format.Format_RGB888)
    image.fill(0)

    for y in range(h):
        for x in range(w):
            px = int(x / scale)
            py = int(y / scale)
            map_x = extent.xMinimum() + (px / src_w) * extent.width()
            map_y = extent.yMaximum() - (py / src_h) * extent.height()
            point = QgsPointXY(map_x, map_y)

            r = g = b = 0
            for band_idx in range(band_count):
                # QGIS API: sample возвращает кортеж (value, bool)
                sample_res = provider.sample(point, band_idx + 1)
                if isinstance(sample_res, tuple):
                    val, is_valid = sample_res
                    if not is_valid:
                        val = None
                else:
                    val = sample_res

                if val is None or val == provider.sourceNoDataValue(band_idx + 1):
                    val = 0
                else:
                    val = max(0, min(255, int(val)))

                if band_idx == 0:
                    r = val
                elif band_idx == 1:
                    g = val
                else:
                    b = val

            if band_count == 1:
                g = b = r

            image.setPixelColor(x, y, QColor(int(r), int(g), int(b)))

    return _qimage_to_png_bytes(image)


def _qimage_to_png_bytes(image: QImage) -> bytes:
    """Сохранение QImage в PNG без зависимости от Qt PNG-драйвера."""
    w, h = image.width(), image.height()
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        for x in range(w):
            c = image.pixelColor(x, y)
            raw.extend((c.red(), c.green(), c.blue()))

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    idat = zlib.compress(bytes(raw), 9)
    return b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            chunk(b"IHDR", ihdr),
            chunk(b"IDAT", idat),
            chunk(b"IEND", b""),
        ]
    )


def geometry_to_png_base64(geometry: QgsGeometry, raster_layer: QgsRasterLayer) -> str:
    """Вырезает область полигона из растра и возвращает base64 PNG."""
    if geometry.isEmpty():
        raise ValueError("Пустая геометрия")

    bbox = geometry.boundingBox()
    provider = raster_layer.dataProvider()
    extent = raster_layer.extent()
    src_w = raster_layer.width()
    src_h = raster_layer.height()

    x_min = max(0, int((bbox.xMinimum() - extent.xMinimum()) / extent.width() * src_w))
    x_max = min(src_w - 1, int((bbox.xMaximum() - extent.xMinimum()) / extent.width() * src_w))
    y_min = max(0, int((extent.yMaximum() - bbox.yMaximum()) / extent.height() * src_h))
    y_max = min(src_h - 1, int((extent.yMaximum() - bbox.yMinimum()) / extent.height() * src_h))

    w = max(1, x_max - x_min + 1)
    h = max(1, y_max - y_min + 1)
    if w > 512:
        scale = 512 / w
        w = 512
        h = max(1, int(h * scale))

    image = QImage(w, h, QImage.Format.Format_RGB888)
    image.fill(128)

    sub_extent = bbox
    for y in range(h):
        for x in range(w):
            map_x = sub_extent.xMinimum() + (x / w) * sub_extent.width()
            map_y = sub_extent.yMaximum() - (y / h) * sub_extent.height()
            point = QgsPointXY(map_x, map_y)
            if not geometry.contains(point):
                continue

            def get_sample(band):
                res = provider.sample(point, band)
                if isinstance(res, tuple):
                    return res[0] if res[1] else 0
                return res if res is not None else 0

            r = get_sample(1)
            g = get_sample(2) if provider.bandCount() >= 2 else r
            b = get_sample(3) if provider.bandCount() >= 3 else r

            image.setPixelColor(x, y, QColor(int(r), int(g), int(b)))

    return base64.b64encode(_qimage_to_png_bytes(image)).decode("ascii")


def add_segmentation_results(
    raster_layer: QgsRasterLayer,
    result: dict[str, Any],
    architecture: str,
    group_name: str = "Agriculture Vision",
    threshold: float | None = None,
) -> QgsVectorLayer | None:
    """Добавляет на карту векторный слой с результатами сегментации."""
    crs = raster_layer.crs().authid()
    thr_tag = f"_thr{threshold:.2f}" if threshold is not None else ""
    layer_name = f"AV_{architecture}{thr_tag}_{raster_layer.name()}"

    fields = QgsFields()
    fields.append(QgsField("label", QVariant.String))
    fields.append(QgsField("confidence", QVariant.Double))
    fields.append(QgsField("area_px", QVariant.Double))
    fields.append(QgsField("source", QVariant.String))
    fields.append(QgsField("threshold", QVariant.Double))

    vector = QgsVectorLayer(f"Polygon?crs={crs}", layer_name, "memory")
    vector.dataProvider().addAttributes(fields)
    vector.updateFields()

    features: list[QgsFeature] = []
    thr_val = float(threshold) if threshold is not None else None

    if architecture == "segformer" and "navigable" in result:
        nav = result["navigable"]
        geom = polygon_px_to_geometry(nav.get("polygon_px", []), raster_layer)
        if geom and nav.get("valid", False):
            feat = QgsFeature(vector.fields())
            feat.setGeometry(geom)
            feat.setAttributes(["field", 1.0, nav.get("area_px", 0), architecture, thr_val])
            features.append(feat)
    elif "detections" in result:
        for det in result["detections"]:
            if not det.get("valid", True):
                continue
            geom = polygon_px_to_geometry(det.get("polygon_px", []), raster_layer)
            if not geom:
                continue
            feat = QgsFeature(vector.fields())
            feat.setGeometry(geom)
            feat.setAttributes(
                [
                    det.get("label", "unknown"),
                    float(det.get("confidence", 0)),
                    float(det.get("area_px", 0)),
                    architecture,
                    thr_val,
                ]
            )
            features.append(feat)

    if not features:
        return None

    vector.dataProvider().addFeatures(features)
    vector.updateExtents()

    QgsProject.instance().addMapLayer(vector)

    root = QgsProject.instance().layerTreeRoot()
    group = root.findGroup(group_name)
    if not group:
        group = root.insertGroup(0, group_name)
    group.insertLayer(0, vector)

    return vector
