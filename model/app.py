"""HTTP API для сегментации полей + раздача web UI."""

from __future__ import annotations

import io
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import cv2
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from model.jobs import JobQueue
from model.pipeline import run_segmentation
from model.runtime import SegmentationRuntime
from model.schemas import HealthResponse, JobStatusResponse, SegmentRequest, SegmentResponse
from model.settings import load_settings

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WEB_DIR = _REPO_ROOT / "web"

_runtime: SegmentationRuntime | None = None
_jobs: JobQueue | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _runtime, _jobs
    settings = load_settings()
    _runtime = SegmentationRuntime(settings)
    try:
        _runtime.load()
    except FileNotFoundError as exc:
        print(f"[model] warning: {exc}")
    _jobs = JobQueue(max_workers=settings.max_concurrent_inferences)
    yield
    if _runtime is not None:
        _runtime.unload()


app = FastAPI(
    title="Segmentation API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _get_runtime() -> SegmentationRuntime:
    if _runtime is None:
        raise HTTPException(503, "Runtime not initialized")
    return _runtime


def _check_upload_size(data: bytes, max_bytes: int) -> None:
    if len(data) > max_bytes:
        raise HTTPException(
            413,
            f"Upload too large ({len(data)} bytes, max {max_bytes})",
        )


def _to_uint8(arr: np.ndarray) -> np.ndarray:
    if arr.dtype == np.uint8:
        return arr
    arr = np.asarray(arr, dtype=np.float32)
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return np.zeros(arr.shape, dtype=np.uint8)
    lo, hi = np.percentile(finite, (2, 98))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        lo, hi = float(np.min(finite)), float(np.max(finite))
    if hi <= lo:
        hi = lo + 1.0
    return np.clip((arr - lo) / (hi - lo) * 255.0, 0, 255).astype(np.uint8)


def _decode_with_rasterio(data: bytes) -> tuple[np.ndarray, np.ndarray | None]:
    import rasterio
    from rasterio.enums import ColorInterp
    from rasterio.io import MemoryFile

    with MemoryFile(data) as mem, mem.open() as ds:
        if ds.count >= 3:
            rgb = np.dstack([_to_uint8(ds.read(i)) for i in (1, 2, 3)])
        else:
            band = _to_uint8(ds.read(1))
            rgb = np.dstack([band, band, band])

        nir = None
        if ds.count >= 4:
            interps = ds.colorinterp or ()
            last = ds.count
            last_interp = interps[last - 1] if len(interps) >= last else None
            if last_interp != ColorInterp.alpha:
                nir = _to_uint8(ds.read(last))
        return rgb, nir


def _looks_like_tiff(data: bytes) -> bool:
    return data[:4] in (b"II*\x00", b"MM\x00*")


def _decode_rgb_nir(data: bytes) -> tuple[np.ndarray, np.ndarray | None]:
    """JPEG/PNG через OpenCV; GeoTIFF — RGB и опционально NIR из 4-го канала."""
    if _looks_like_tiff(data):
        try:
            return _decode_with_rasterio(data)
        except Exception:
            pass

    bgr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if bgr is not None:
        return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), None

    try:
        return _decode_with_rasterio(data)
    except Exception:
        pass

    try:
        from PIL import Image

        img = Image.open(io.BytesIO(data))
        if img.mode != "RGB":
            img = img.convert("RGB")
        return np.asarray(img, dtype=np.uint8), None
    except Exception as exc:
        raise ValueError("Invalid RGB image") from exc


def _decode_nir(data: bytes) -> np.ndarray:
    gray = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
    if gray is not None:
        return gray
    rgb, _ = _decode_rgb_nir(data)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)


def _run_inference(
    rt: SegmentationRuntime,
    rgb_bytes: bytes,
    nir_bytes: bytes | None,
    req: SegmentRequest,
) -> SegmentResponse:
    sem = rt.acquire_inference_slot()
    with sem:
        rgb_arr, embedded_nir = _decode_rgb_nir(rgb_bytes)
        nir_arr = _decode_nir(nir_bytes) if nir_bytes else embedded_nir
        return run_segmentation(rt, rgb=rgb_arr, nir=nir_arr, request=req)


def _health_payload() -> HealthResponse:
    rt = _get_runtime()
    loaded = rt.is_loaded
    models = ["segformer"] if loaded else []
    hint = None
    if not loaded:
        hint = (
            "На ML-сервере нет весов моделей (best_iou.pth). "
            "Положите чекпоинт в model/weights/best_iou.pth"
        )
    return HealthResponse(
        status="ok",
        model_loaded=loaded,
        device=str(rt.device) if loaded else None,
        fp16=rt.meta.get("fp16_active") if loaded else None,
        checkpoint=rt.meta.get("checkpoint_path") if loaded else None,
        available_models=models,
        hint=hint,
    )


async def _read_optional_upload(upload: UploadFile | None, max_bytes: int) -> bytes | None:
    if upload is None:
        return None
    data = await upload.read()
    if not data:
        return None
    _check_upload_size(data, max_bytes)
    return data


async def _segment_from_bytes(
    rgb_bytes: bytes,
    nir_bytes: bytes | None,
    req: SegmentRequest,
    wait: bool,
) -> SegmentResponse | dict[str, str]:
    rt = _get_runtime()
    if not rt.is_loaded:
        raise HTTPException(503, "Model weights not loaded")
    if _jobs is None:
        raise HTTPException(503, "Job queue not initialized")

    if wait:
        try:
            return _run_inference(rt, rgb_bytes, nir_bytes, req)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(500, f"Inference failed: {exc}") from exc

    job_id = _jobs.submit(lambda: _run_inference(rt, rgb_bytes, nir_bytes, req))
    return {"job_id": job_id, "status": "queued"}


def _check_architecture(architecture: str) -> None:
    arch = (architecture or "segformer").strip().lower()
    if arch in {"", "segformer", "yolo"}:
        # YOLO — классификация культур, не сегментация границ. Всегда SegFormer.
        return
    raise HTTPException(400, f"Unknown architecture: {arch}")


@app.get("/health", response_model=HealthResponse)
@app.get("/api/v1/segmentation/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return _health_payload()


@app.get("/ready")
def ready() -> JSONResponse:
    rt = _get_runtime()
    if not rt.is_loaded:
        return JSONResponse(
            status_code=503,
            content={"ready": False, "reason": "checkpoint not loaded"},
        )
    return JSONResponse({"ready": True})


@app.post("/v1/segment")
async def segment(
    rgb: Annotated[UploadFile, File(description="RGB image (JPEG/PNG)")],
    nir: Annotated[UploadFile | None, File(description="Optional NIR grayscale")] = None,
    threshold: float | None = Form(None),
    tta: bool | None = Form(None),
    use_sliding: bool = Form(False),
    include_mask_png: bool = Form(False),
    include_geojson: bool | None = Form(None),
    wait: bool = Form(
        True,
        description=(
            "true — ответ сразу с результатом (удобно для curl/малых снимков); "
            "false — job_id и опрос GET /v1/jobs/{id} (для долгого инференса)"
        ),
    ),
) -> SegmentResponse | dict[str, str]:
    """
    Один эндпоинт сегментации.

    Параметр `wait` вместо двух разных URL: долгий прогон не обязан держать HTTP-соединение.
    """
    rt = _get_runtime()
    rgb_bytes = await rgb.read()
    _check_upload_size(rgb_bytes, rt.settings.max_upload_bytes)
    nir_bytes = await _read_optional_upload(nir, rt.settings.max_upload_bytes)
    req = SegmentRequest(
        threshold=threshold,
        tta=tta,
        use_sliding=use_sliding,
        include_mask_png=include_mask_png,
        include_geojson=include_geojson,
    )
    return await _segment_from_bytes(rgb_bytes, nir_bytes, req, wait)


@app.post("/api/v1/segmentation/segment")
async def ui_segment(
    file: Annotated[UploadFile | None, File(description="Снимок из web UI (file)")] = None,
    rgb: Annotated[UploadFile | None, File(description="Алиас RGB")] = None,
    nir: Annotated[UploadFile | None, File(description="Optional NIR grayscale")] = None,
    architecture: str = Query("segformer"),
    threshold: float | None = Query(None),
    include_mask_png: bool = Query(False),
    include_geojson: bool = Query(False),
    tta: bool | None = Query(None),
    use_sliding: bool = Query(False),
    wait: bool = Query(True),
) -> SegmentResponse | dict[str, str]:
    """Контракт Agriculture Vision UI: multipart `file` + query threshold.
    `architecture` игнорируется: границы всегда SegFormer."""
    _check_architecture(architecture)
    rt = _get_runtime()
    upload = file or rgb
    if upload is None:
        raise HTTPException(400, "Missing image: send multipart field `file`")
    rgb_bytes = await upload.read()
    if not rgb_bytes:
        raise HTTPException(400, "Empty image upload")
    _check_upload_size(rgb_bytes, rt.settings.max_upload_bytes)
    nir_bytes = await _read_optional_upload(nir, rt.settings.max_upload_bytes)
    req = SegmentRequest(
        threshold=threshold,
        tta=tta,
        use_sliding=use_sliding,
        include_mask_png=include_mask_png,
        include_geojson=include_geojson,
    )
    return await _segment_from_bytes(rgb_bytes, nir_bytes, req, wait)


@app.get("/v1/jobs/{job_id}", response_model=JobStatusResponse)
def job_status(job_id: str) -> JobStatusResponse:
    if _jobs is None:
        raise HTTPException(503, "Job queue not initialized")
    status = _jobs.get(job_id)
    if status is None:
        raise HTTPException(404, "Job not found")
    return status


if _WEB_DIR.is_dir():

    @app.get("/", include_in_schema=False)
    def web_index() -> FileResponse:
        return FileResponse(_WEB_DIR / "index.html")

    app.mount("/", StaticFiles(directory=_WEB_DIR, html=True), name="web")
