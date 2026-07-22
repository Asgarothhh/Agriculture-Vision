"""Agriculture Vision FastAPI backend — контракт совместим с api_client.py / mock_client.py."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from inference import (
    CROP_CLASSES,
    available_segmentation_models,
    get_device_name,
    run_classification,
    run_segmentation,
    weights_status,
)
from paths import API_VERSION, SEGFORMER_WEIGHTS, YOLO_WEIGHTS, ensure_models_dir

app = FastAPI(
    title="Agriculture Vision API",
    version=API_VERSION,
    description="Демо-backend для QGIS-плагина Agriculture Vision (LAN).",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ClassifyRequest(BaseModel):
    image_base64: str = Field(..., description="PNG/JPEG в base64")
    threshold: Optional[float] = Field(None, ge=0.0, le=1.0)


def _parse_bool(value: str | bool | None, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


@app.on_event("startup")
def _startup() -> None:
    ensure_models_dir()


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "message": "Agriculture Vision API",
        "version": API_VERSION,
        "mode": "api",
        "docs": "/docs",
    }


@app.get("/api/v1/segmentation/health")
def segmentation_health(
    architecture: str = Query("all", description="yolo | segformer | all"),
) -> dict[str, Any]:
    arch = architecture.lower().strip()
    status = weights_status()
    device = get_device_name()
    available = available_segmentation_models()

    if arch == "yolo":
        loaded = status["yolo"]["present"]
        ok_models = ["yolo"] if loaded else []
    elif arch == "segformer":
        loaded = status["segformer"]["present"]
        ok_models = ["segformer"] if loaded else []
    else:
        loaded = bool(available)
        ok_models = available

    health_status = "healthy" if loaded else "degraded"
    return {
        "status": health_status,
        "model_loaded": loaded,
        "device": device,
        "available_models": ok_models,
        "requested_architecture": arch,
        "weights": status,
        "mode": "api",
        "hint": None
        if loaded
        else (
            f"Положите веса в {status['models_dir']}: "
            "best_iou.pth (segformer), yolo_best.pt (yolo)"
        ),
    }


@app.get("/api/v1/segmentation/models")
def list_models() -> dict[str, Any]:
    return {
        "available_models": available_segmentation_models(),
        "all_architectures": ["yolo", "segformer"],
        "weights": weights_status(),
        "mode": "api",
    }


@app.post("/api/v1/segmentation/segment")
async def segment(
    file: UploadFile = File(..., description="Изображение (PNG/JPEG), поле multipart: file"),
    architecture: str = Query("yolo"),
    threshold: Optional[float] = Query(None, ge=0.0, le=1.0),
    tta: str = Query("false"),
    include_mask_png: str = Query("false"),
    include_geojson: str = Query("false"),
) -> dict[str, Any]:
    arch = architecture.lower().strip()
    if arch not in {"yolo", "segformer"}:
        raise HTTPException(
            status_code=400,
            detail=f"Неизвестная architecture={architecture!r}. Допустимо: yolo, segformer",
        )

    use_tta = _parse_bool(tta, False)
    want_geojson = _parse_bool(include_geojson, False)
    # include_mask_png зарезервирован контрактом; маску пока не отдаём (как client: false)
    _ = _parse_bool(include_mask_png, False)

    weights = weights_status()
    if arch == "yolo" and not weights["yolo"]["present"]:
        raise HTTPException(
            status_code=503,
            detail=(
                f"Веса YOLO отсутствуют: {YOLO_WEIGHTS}. "
                f"Скопируйте yolo_best.pt в {weights['models_dir']}"
            ),
        )
    if arch == "segformer" and not weights["segformer"]["present"]:
        raise HTTPException(
            status_code=503,
            detail=(
                f"Веса SegFormer отсутствуют: {SEGFORMER_WEIGHTS}. "
                f"Скопируйте best_iou.pth в {weights['models_dir']}"
            ),
        )

    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Пустой файл в поле 'file'")

    try:
        return run_segmentation(
            image_bytes,
            architecture=arch,
            threshold=threshold,
            tta=use_tta,
            include_geojson=want_geojson,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка инференса: {exc}",
        ) from exc


@app.get("/api/v1/classification/health")
def classification_health() -> dict[str, Any]:
    return {
        "status": "degraded",
        "classifier_loaded": False,
        "num_crop_classes": len(CROP_CLASSES),
        "crop_classes": CROP_CLASSES,
        "mode": "api-stub",
        "hint": "Классификатор пока stub (случайные вероятности), endpoint живой.",
    }


@app.post("/api/v1/classification/classify")
def classify(body: ClassifyRequest) -> dict[str, Any]:
    try:
        return run_classification(body.image_base64, threshold=body.threshold)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка классификации: {exc}",
        ) from exc
