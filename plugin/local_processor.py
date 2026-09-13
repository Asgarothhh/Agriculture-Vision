import os
import sys
import numpy as np
from pathlib import Path
from qgis.PyQt.QtCore import QThread, pyqtSignal

# ==========================================================
# ФИКС ДЛЯ QGIS (ОБХОД ОШИБКИ 'isatty' И ПРОГРЕСС-БАРОВ)
# ==========================================================
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"


class DummyStream:
  def write(self, data): pass

  def flush(self): pass

  def isatty(self): return False


if sys.stdout is None: sys.stdout = DummyStream()
if sys.stderr is None: sys.stderr = DummyStream()
if not hasattr(sys.stdout, 'isatty'): sys.stdout.isatty = lambda: False
if not hasattr(sys.stderr, 'isatty'): sys.stderr.isatty = lambda: False
# ==========================================================

# Динамически добавляем путь к плагину, чтобы Python увидел папку field_detecter
PLUGIN_DIR = Path(__file__).parent.resolve()
if str(PLUGIN_DIR) not in sys.path:
  sys.path.append(str(PLUGIN_DIR))

from .constants import YOLO_CLASSES, SEGFORMER_CLASSES, CROP_CLASSES
from .layer_utils import raster_layer_to_png_bytes


def _import_cv2():
  try:
    import cv2
    return cv2
  except ImportError as e:
    raise ImportError(
      "Не найден модуль cv2 (opencv). Установите в Python QGIS:\n"
      "/Applications/QGIS-final-4_2_0.app/Contents/MacOS/python3.12 "
      "-m pip install --user \"opencv-python-headless>=4.8,<5\""
    ) from e


class LocalSegmentationWorker(QThread):
  progress = pyqtSignal(int)
  finished = pyqtSignal(dict)
  error = pyqtSignal(str)

  def __init__(self, raster_layer, architecture, threshold):
    super().__init__()
    self.raster_layer = raster_layer
    self.architecture = architecture.lower()
    self.threshold = threshold

    self.segformer_path = PLUGIN_DIR / "models" / "best_iou.pth"
    self.yolo_path = PLUGIN_DIR / "models" / "yolo_best.pt"

  def run(self):
    try:
      if not self.raster_layer or not self.raster_layer.isValid():
        self.error.emit("Неверный или пустой растровый слой.")
        return

      self.progress.emit(5)

      # 1. Читаем изображение из QGIS
      try:
        cv2 = _import_cv2()
        png_bytes = raster_layer_to_png_bytes(self.raster_layer)
        nparr = np.frombuffer(png_bytes, np.uint8)
        rgb_image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        rgb_image = cv2.cvtColor(rgb_image, cv2.COLOR_BGR2RGB)
      except Exception as e:
        self.error.emit(f"Ошибка чтения растра: {str(e)}")
        return

      self.progress.emit(20)
      result = {}

      # ==========================================
      # ИНФЕРЕНС ВАШЕГО SEGFORMER (ViT 4-ch)
      # ==========================================
      if self.architecture == "segformer":
        if not self.segformer_path.exists():
          self.error.emit(f"Чекпоинт не найден: {self.segformer_path}")
          return

        self.progress.emit(30)
        try:
          import torch
          import torch.nn.functional as F
          from field_detecter.seg_infer import (
            load_segformer_checkpoint,
            load_rgb_nir_from_array,
            prob_to_mask
          )
          from field_detecter.polygon import mask_to_navigable_polygon
        except ImportError as e:
          self.error.emit(f"Ошибка импорта: {e}")
          return

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        self.progress.emit(40)
        # Подготовка 4-х каналов
        image_4ch = load_rgb_nir_from_array(rgb_image, None)

        self.progress.emit(55)
        # Загрузка модели (теперь пройдет быстро, так как веса уже скачаны)
        model, meta = load_segformer_checkpoint(self.segformer_path, device=device)
        model.eval()

        self.progress.emit(75)
        # Инференс
        x = torch.from_numpy(image_4ch).unsqueeze(0).to(device)
        use_amp = (device.type == "cuda")

        with torch.no_grad():
          with torch.autocast(device_type="cuda", enabled=use_amp):
            logits = model(x).logits

          if logits.shape[-2:] != image_4ch.shape[-2:]:
            logits = F.interpolate(
              logits.float(),
              size=image_4ch.shape[-2:],
              mode="bilinear",
              align_corners=False,
            )
          else:
            logits = logits.float()

          prob = logits.softmax(dim=1)[0, 1].cpu().numpy().astype(np.float32)

        self.progress.emit(90)
        # Постобработка
        mask, _, _ = prob_to_mask(prob, self.threshold)

        poly_raw = mask_to_navigable_polygon(
          mask,
          headland_margin_px=12,
          simplify_tolerance=2.5,
          min_area_px=500.0,
        )

        polygon_points = []
        area_px = 0.0

        if poly_raw.get("valid"):
          polygon_points = [(int(p[0]), int(p[1])) for p in poly_raw["polygon_px"]]
          area_px = float(poly_raw["area_px"])

        result = {
          "navigable": {
            "valid": poly_raw.get("valid", False),
            "polygon_px": polygon_points,
            "area_px": area_px
          }
        }

        del model
        if device.type == "cuda":
          torch.cuda.empty_cache()

      # ==========================================
      # ИНФЕРЕНС YOLO
      # ==========================================
      elif self.architecture == "yolo":
        if not self.yolo_path.exists():
          self.error.emit(f"Файл весов не найден: {self.yolo_path}")
          return

        self.progress.emit(30)
        try:
          from ultralytics import YOLO
        except ImportError:
          self.error.emit("Библиотека ultralytics не установлена.")
          return

        model = YOLO(str(self.yolo_path))
        self.progress.emit(60)

        outputs = model.predict(
          source=rgb_image,
          imgsz=640,
          conf=self.threshold,
          iou=0.5,
          verbose=False
        )

        self.progress.emit(80)
        detections = []
        res = outputs[0]

        if res.boxes is not None and len(res.boxes) > 0:
          boxes = res.boxes.cpu().numpy()
          masks_xy = res.masks.xy if res.masks is not None else []

          for idx, box in enumerate(boxes):
            class_id = int(box.cls[0])
            conf = float(box.conf[0])
            label = YOLO_CLASSES.get(class_id, f"class_{class_id}")

            polygon_points = []
            area_px = 0.0
            if idx < len(masks_xy) and len(masks_xy[idx]) > 0:
              polygon_points = [(int(x), int(y)) for x, y in masks_xy[idx]]
              contour_array = np.array(polygon_points, dtype=np.int32)
              area_px = float(_import_cv2().contourArea(contour_array))

            detections.append({
              "label": label,
              "confidence": conf,
              "polygon_px": polygon_points,
              "area_px": area_px,
              "valid": area_px > 0
            })

        result = {"detections": detections}
        del model

      self.progress.emit(100)
      self.finished.emit(result)

    except Exception as e:
      self.error.emit(f"Критическая ошибка инференса: {str(e)}")


class LocalClassifier:
  """Заглушка классификации"""

  @staticmethod
  def classify(polygon_id: str) -> dict:
    import random
    probs = [random.random() for _ in CROP_CLASSES]
    total = sum(probs)
    normalized_probs = [p / total for p in probs]
    items = [{"crop_class": crop, "probability": prob} for crop, prob in zip(CROP_CLASSES, normalized_probs)]
    items.sort(key=lambda x: x["probability"], reverse=True)
    return {
      "ok": True,
      "predicted": items[0]["crop_class"],
      "confidence": items[0]["probability"],
      "probabilities": items
    }
