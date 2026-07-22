"""Пути к весам моделей (Docker / локально)."""

from __future__ import annotations

import os
from pathlib import Path

# В Docker: MODELS_DIR=/models, PLUGIN_DIR=/app/plugin
REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_DIR = Path(os.environ.get("PLUGIN_DIR", str(REPO_ROOT / "plugin"))).resolve()
MODELS_DIR = Path(os.environ.get("MODELS_DIR", str(PLUGIN_DIR / "models"))).resolve()

SEGFORMER_WEIGHTS = MODELS_DIR / "best_iou.pth"
YOLO_WEIGHTS = MODELS_DIR / "yolo_best.pt"

API_VERSION = "1.1.0"


def ensure_models_dir() -> Path:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    return MODELS_DIR
