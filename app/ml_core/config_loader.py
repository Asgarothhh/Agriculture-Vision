"""Загрузка конфигурации ML-ядра."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parent


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    if path is None:
        path = _ROOT / "config" / "agvision.yaml"
    path = Path(path)
    if not path.is_absolute():
        cwd_path = Path.cwd() / path
        path = cwd_path if cwd_path.is_file() else _ROOT / path
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def project_root() -> Path:
    return _ROOT
