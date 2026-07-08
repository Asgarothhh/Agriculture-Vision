"""Загрузка config/agvision.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parents[1]


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    if path is None:
        path = _ROOT / "config" / "agvision.yaml"
    path = Path(path)
    if not path.is_absolute():
        path = _ROOT / path
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def project_root() -> Path:
    return _ROOT
