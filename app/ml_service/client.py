"""In-process ML runtime facade (no remote ML server)."""

from app.ml_service.runtime import health, infer, infer_sync, load_models

__all__ = ["health", "infer", "infer_sync", "load_models"]
