from pathlib import Path

import pytest

from app.ml_service.runtime import ModelRuntime, runtime
from app.ml_service.schemas import InferenceRequest, InferenceResponse


ROOT = Path(__file__).resolve().parents[1]


def test_weight_files_exist():
    yolo = ROOT / "config" / "yolo_best.pt"
    seg = ROOT / "config" / "segformer_best.pt"
    engine = ModelRuntime()
    if not yolo.is_file() or yolo.stat().st_size == 0:
        pytest.skip("YOLO weights missing: config/yolo_best.pt")
    found_yolo = engine._resolve("config/yolo_best.pt")
    assert found_yolo is not None
    assert found_yolo.stat().st_size > 0
    if not seg.is_file() or seg.stat().st_size == 0:
        pytest.skip("SegFormer weights missing: config/segformer_best.pt")
    found_seg = engine._resolve("config/segformer_best.pt")
    assert found_seg is not None
    assert found_seg.stat().st_size > 0


def test_resolve_skips_directory(tmp_path, monkeypatch):
    engine = ModelRuntime()
    unpacked = tmp_path / "best_iou"
    unpacked.mkdir()
    (unpacked / "data.pkl").write_bytes(b"not-a-checkpoint")
    monkeypatch.setattr("app.ml_service.runtime.ROOT", tmp_path)
    assert engine._resolve(str(unpacked)) is None


@pytest.mark.ml
def test_load_models_real_weights():
    yolo = ROOT / "config" / "yolo_best.pt"
    seg = ROOT / "config" / "segformer_best.pt"
    if not yolo.is_file() and not (seg.is_file() and seg.stat().st_size > 0):
        pytest.skip("No local weight files")
    engine = ModelRuntime()
    payload = engine.load_models()
    codes = {item["code"] for item in payload["models"]}
    assert codes == {"yolo_seg_26", "segformer"}


def test_load_models_invoked_and_health_lists_codes(monkeypatch):
    calls = {"n": 0}

    def fake_load(self):
        calls["n"] += 1
        self._loaded = {"yolo_seg_26": True, "segformer": True}
        self._paths = {
            "yolo_seg_26": str(ROOT / "config" / "yolo_best.pt"),
            "segformer": str(ROOT / "config" / "segformer_best.pt"),
        }
        return self.health()

    monkeypatch.setattr(ModelRuntime, "load_models", fake_load)
    payload = fake_load(runtime)
    assert calls["n"] == 1
    codes = {item["code"] for item in payload["models"]}
    assert codes == {"yolo_seg_26", "segformer"}
    assert payload["status"] == "ready"


def test_remap_encoder_keys_to_stages():
    from app.ml_core.seg_remap import remap_segformer_state_dict

    state = {
        "model.segformer.encoder.patch_embeddings.0.proj.weight": 1,
        "model.segformer.encoder.block.0.0.attention.self.query.weight": 2,
        "model.segformer.encoder.block.0.0.attention.self.sr.weight": 3,
        "model.segformer.encoder.block.1.2.mlp.dense1.weight": 4,
        "model.decode_head.linear_c.0.proj.weight": 6,
        "model.decode_head.classifier.weight": 5,
    }
    target = {
        "model.segformer.stages.0.patch_embeddings.proj.weight",
        "model.segformer.stages.0.blocks.0.attention.q_proj.weight",
        "model.segformer.stages.0.blocks.0.attention.sequence_reduction.sequence_reduction.weight",
        "model.segformer.stages.1.blocks.2.mlp.fc1.weight",
        "model.decode_head.linear_projections.0.proj.weight",
        "model.decode_head.classifier.weight",
    }
    remapped = remap_segformer_state_dict(state, target)
    assert remapped["model.segformer.stages.0.patch_embeddings.proj.weight"] == 1
    assert remapped["model.segformer.stages.0.blocks.0.attention.q_proj.weight"] == 2
    assert remapped["model.segformer.stages.0.blocks.0.attention.sequence_reduction.sequence_reduction.weight"] == 3
    assert remapped["model.segformer.stages.1.blocks.2.mlp.fc1.weight"] == 4
    assert remapped["model.decode_head.linear_projections.0.proj.weight"] == 6
    assert remapped["model.decode_head.classifier.weight"] == 5


def test_infer_is_called(monkeypatch):
    called = {"n": 0}

    def fake_infer(self, file_bytes, filename, request):
        called["n"] += 1
        assert request.model in {"yolo_seg_26", "segformer"}
        return InferenceResponse(model=request.model, polygons=[], points=[])

    monkeypatch.setattr(ModelRuntime, "infer", fake_infer)
    result = fake_infer(runtime, b"abc", "x.png", InferenceRequest(model="segformer", confidence=0.4))
    assert called["n"] == 1
    assert result.model == "segformer"


@pytest.fixture
def ml_health_key(monkeypatch):
    import uuid

    from app.ml_service import health_store

    monkeypatch.setattr(health_store, "KEY", f"test:ml:health:{uuid.uuid4().hex}")
    yield health_store
    health_store.clear_health()


def _worker_payload(segformer_loaded: bool = True) -> dict:
    return {
        "status": "ready" if segformer_loaded else "unavailable",
        "models": [
            {"code": "yolo_seg_26", "loaded": False, "weights": None, "error": "weights file not found"},
            {"code": "segformer", "loaded": segformer_loaded, "weights": "/app/config/segformer_best.pt", "error": None},
        ],
    }


def test_health_store_roundtrip(ml_health_key):
    ml_health_key.publish_health(_worker_payload())
    stored = ml_health_key.read_health()
    assert stored["status"] == "ready"
    assert "updated_at" in stored
    ml_health_key.clear_health()
    assert ml_health_key.read_health() is None


def test_api_health_uses_worker_status(ml_health_key, monkeypatch):
    from app.core.celery_app import celery_app

    runtime.reset()
    monkeypatch.setattr(celery_app.control, "ping", lambda **_kw: [{"worker@pod": {"ok": "pong"}}])
    ml_health_key.publish_health(_worker_payload())
    health = ml_health_key.get_ml_health()
    assert health["status"] == "ready"
    seg = next(m for m in health["models"] if m["code"] == "segformer")
    assert seg["loaded"] is True


def test_api_health_worker_offline(ml_health_key, monkeypatch):
    from app.core.celery_app import celery_app

    runtime.reset()
    monkeypatch.setattr(celery_app.control, "ping", lambda **_kw: [])
    ml_health_key.publish_health(_worker_payload())
    health = ml_health_key.get_ml_health()
    assert health["status"] == "unavailable"
    assert all(not m["loaded"] and m["error"] == "ML worker offline" for m in health["models"])


def test_api_health_worker_not_reported(ml_health_key):
    runtime.reset()
    health = ml_health_key.get_ml_health()
    assert health["status"] == "unavailable"
    assert {m["code"] for m in health["models"]} == {"yolo_seg_26", "segformer"}
    assert all(m["error"] == "ML worker has not reported model status" for m in health["models"])


def test_run_segmentation_is_called_with_its_real_signature(monkeypatch):
    import ast
    import sys
    import types

    import importlib.util

    import numpy as np

    # app/segmentation_service/__init__ imports torch; load the pydantic schemas file alone.
    spec = importlib.util.spec_from_file_location(
        "segmentation_service.schemas", ROOT / "app" / "segmentation_service" / "schemas.py"
    )
    schemas = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(schemas)
    PolygonItem, PolygonPayload = schemas.PolygonItem, schemas.PolygonPayload
    SegmentMetrics, SegmentResponse = schemas.SegmentMetrics, schemas.SegmentResponse

    # The real pipeline needs torch and top-level ml_core imports; read its signature from source.
    source = (ROOT / "app" / "segmentation_service" / "pipeline.py").read_text(encoding="utf-8")
    func = next(
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == "run_segmentation"
    )
    assert [a.arg for a in func.args.args] == ["runtime"]
    assert {"rgb", "request", "on_progress"} <= {a.arg for a in func.args.kwonlyargs}

    seen = {}

    def fake_run_segmentation(rt, *, rgb_path=None, nir_path=None, rgb=None, nir=None, request=None, on_progress=None):
        seen["shape"] = rgb.shape
        seen["threshold"] = request.threshold
        return SegmentResponse(
            navigable=PolygonPayload(polygon_px=[], area_px=0.0, valid=False),
            polygons=[PolygonItem(polygon_px=[(10, 10), (50, 10), (50, 40), (10, 40)], area_px=1200.0)],
            image_hw=(100, 200),
            checkpoint="x",
            metrics=SegmentMetrics(
                threshold_used=0.4, area_frac=0.1, prob_mean=0.5, prob_std=0.1,
                mode="prob_only", inference_ms=1.0, fp16=False, device="cpu",
            ),
        )

    fake_pipeline = types.ModuleType("segmentation_service.pipeline")
    fake_pipeline.run_segmentation = fake_run_segmentation
    monkeypatch.setitem(sys.modules, "segmentation_service", types.ModuleType("segmentation_service"))
    monkeypatch.setitem(sys.modules, "segmentation_service.pipeline", fake_pipeline)
    monkeypatch.setitem(sys.modules, "segmentation_service.schemas", schemas)

    engine = ModelRuntime()
    engine._segformer = object()
    image = np.zeros((200, 400, 3), dtype=np.uint8)  # pipeline reported 100x200 -> scale x2
    payload = engine._run_segformer(image, 0.4)
    assert seen == {"shape": (200, 400, 3), "threshold": 0.4}
    assert len(payload["polygons"]) == 1
    poly = payload["polygons"][0]
    assert poly["class_id"] == 2
    ring = poly["geometry"]["coordinates"][0]
    assert ring[0] == ring[-1]
    assert ring[1] == [100.0, 20.0]


def test_yolo_classes_map_to_spec_categories():
    import numpy as np

    from app.ml_service.runtime import POINT_CLASS_IDS, yolo_class_id

    names = {0: "double_plant", 1: "drydown", 2: "endrow", 3: "nutrient_deficiency", 4: "planter_skip",
             5: "storm_damage", 6: "water", 7: "waterway", 8: "weed_cluster"}
    assert [yolo_class_id(names, i) for i in range(9)] == [21, 22, 23, 27, 26, 28, 4, 24, 25]
    assert yolo_class_id(names, 42) is None
    assert yolo_class_id(["water", "unknown_thing"], 1) is None
    assert 26 in POINT_CLASS_IDS

    class Boxes:
        cls = np.array([6, 4, 3])
        conf = np.array([0.9, 0.8, 0.7])

    square = np.array([[0, 0], [10, 0], [10, 10], [0, 10]], dtype=float)

    class Masks:
        xy = [square, square + 20, square + 40]

    class Result:
        boxes = Boxes()
        masks = Masks()

    class FakeYolo:
        def __init__(self):
            self.names = names

        def predict(self, image, conf, verbose, **kwargs):
            self.image = image
            return [Result()]

    engine = ModelRuntime()
    engine._yolo = FakeYolo()
    rgb = np.zeros((32, 32, 3), dtype=np.uint8)
    rgb[..., 0] = 255  # pure red in RGB
    payload = engine._run_yolo(rgb, 0.25)
    assert engine._yolo.image[0, 0].tolist() == [0, 0, 255]  # handed to YOLO as BGR
    assert [p["class_id"] for p in payload["polygons"]] == [4, 27]
    assert [p["class_id"] for p in payload["points"]] == [26]
    assert payload["points"][0]["geometry"]["coordinates"] == [25.0, 25.0]


def test_api_health_reports_models_loading(ml_health_key, monkeypatch):
    from app.core.celery_app import celery_app

    runtime.reset()
    monkeypatch.setattr(celery_app.control, "ping", lambda **_kw: [{"worker@pod": {"ok": "pong"}}])
    ml_health_key.publish_health({"status": "loading", "models": []})
    health = ml_health_key.get_ml_health()
    assert health["status"] == "loading"
    assert {m["code"] for m in health["models"]} == {"yolo_seg_26", "segformer"}
    assert all(not m["loaded"] for m in health["models"])


def test_celery_does_not_kill_worker_while_models_load():
    from app.core.celery_app import celery_app

    # Celery's default is 4 s; loading torch + YOLO + SegFormer takes much longer.
    assert celery_app.conf.worker_proc_alive_timeout >= 60


def test_yolo_tile_windows_cover_image_with_overlap():
    from app.ml_service.runtime import tile_windows

    assert tile_windows(500, 600, 640) == [(0, 0, 600, 500)]
    windows = tile_windows(2000, 3000, 640, 0.2)
    covered = set()
    for x0, y0, x1, y1 in windows:
        assert x1 - x0 == 640 and y1 - y0 == 640
        covered.update((x, y) for x in range(x0, x1, 40) for y in range(y0, y1, 40))
    assert max(x1 for _, _, x1, _ in windows) == 3000
    assert max(y1 for _, _, _, y1 in windows) == 2000
    xs = sorted({x0 for x0, _, _, _ in windows})
    assert all(b - a <= 512 for a, b in zip(xs, xs[1:]))  # 20 % overlap


def test_yolo_train_size_reads_model_overrides():
    from app.ml_service.runtime import YOLO_DEFAULT_IMGSZ, yolo_train_size

    class M:
        overrides = {"imgsz": 512}

    class N:
        overrides = {"imgsz": [640, 640]}

    assert yolo_train_size(M()) == 512
    assert yolo_train_size(N()) == 640
    assert yolo_train_size(object()) == YOLO_DEFAULT_IMGSZ


def test_merge_sliced_detections_joins_pieces_and_drops_duplicates():
    from app.ml_service.runtime import merge_sliced_detections

    def poly(cid, conf, x0, y0, x1, y1):
        ring = [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]
        return {"class_id": cid, "confidence": conf, "geometry": {"type": "Polygon", "coordinates": [ring]}}

    def point(cid, conf, x, y):
        return {"class_id": cid, "confidence": conf, "geometry": {"type": "Point", "coordinates": [x, y]}}

    polygons = [
        poly(22, 0.6, 0, 0, 520, 100),  # one field cut by the tile border…
        poly(22, 0.8, 500, 0, 900, 100),  # …seen again by the next tile
        poly(22, 0.5, 2000, 2000, 2100, 2100),  # a separate object stays separate
        poly(4, 0.7, 0, 0, 520, 100),  # other class is not merged into class 22
    ]
    points = [point(26, 0.9, 100, 100), point(26, 0.6, 103, 101), point(26, 0.7, 400, 400)]
    merged, kept = merge_sliced_detections(polygons, points)
    by_class = {}
    for item in merged:
        by_class.setdefault(item["class_id"], []).append(item)
    assert len(by_class[22]) == 2
    big = next(it for it in by_class[22] if min(x for x, _ in it["geometry"]["coordinates"][0]) == 0)
    assert max(x for x, _ in big["geometry"]["coordinates"][0]) == 900
    assert big["confidence"] == 0.8
    assert len(by_class[4]) == 1
    assert sorted(p["geometry"]["coordinates"] for p in kept) == [[100, 100], [400, 400]]


def test_run_yolo_slices_large_snapshots():
    import numpy as np

    names = {6: "water", 4: "planter_skip"}
    square = np.array([[10, 10], [60, 10], [60, 60], [10, 60]], dtype=float)

    class Boxes:
        def __init__(self, n):
            self.cls = np.array([6, 4][:n])
            self.conf = np.array([0.9, 0.8][:n])

    class Masks:
        xy = [square, square + 100]

    class Result:
        boxes = Boxes(2)
        masks = Masks()

    class FakeYolo:
        overrides = {"imgsz": 640}

        def __init__(self):
            self.names = names
            self.calls = []

        def predict(self, image, conf, verbose, **kwargs):
            self.calls.append((len(image) if isinstance(image, list) else 1, kwargs.get("imgsz")))
            batch = image if isinstance(image, list) else [image]
            for crop in batch:
                assert crop.shape[0] <= 640 and crop.shape[1] <= 640
            return [Result() for _ in batch]

    engine = ModelRuntime()
    engine._yolo = FakeYolo()
    payload = engine._run_yolo(np.zeros((1500, 2400, 3), dtype=np.uint8), 0.25)
    tiles = sum(n for n, _ in engine._yolo.calls)
    assert tiles > 4
    assert all(imgsz == 640 for _, imgsz in engine._yolo.calls)
    # every tile found «water» at its own offset → polygons in full-image coordinates
    xs = [min(x for x, _ in p["geometry"]["coordinates"][0]) for p in payload["polygons"]]
    assert max(xs) > 1500
    assert all(p["class_id"] == 4 for p in payload["polygons"])
    assert all(p["class_id"] == 26 for p in payload["points"])


def test_pixel_size_from_geographic_and_projected_transforms():
    from app.ml_service.runtime import pixel_size_m

    # 1° of longitude at 53.5°N ≈ 66 km, so 0.00001° per pixel ≈ 0.66 m (x); latitude ≈ 1.11 m (y).
    m = pixel_size_m([27.0, 1e-5, 0, 53.5, 0, -1e-5], "EPSG:4326", 1000)
    assert 0.85 < m < 0.95  # mean of ~0.67 and ~1.11
    assert pixel_size_m([500000.0, 0.3, 0, 5900000.0, 0, -0.3], "EPSG:32635", 1000) == 0.3
    assert pixel_size_m(None, "EPSG:4326", 100) is None
    assert pixel_size_m([0, 0, 0, 0, 0, 0], "EPSG:4326", 100) is None


def test_choose_working_scale_matches_training_scale_within_budget():
    from app.ml_service.runtime import choose_working_scale, count_windows

    # small AOI at 0.35 m/px: up to 2× upscale only (0.175 m/px), few windows
    work, h, w, n = choose_working_scale(
        400, 500, 0.35, target_m_per_px=0.1, tile=512, stride=384, max_windows=49
    )
    assert abs(work - 0.175) < 1e-9 and (h, w) == (800, 1000) and n == count_windows(800, 1000, 512, 384)

    # finer source than the target: downscale to exactly 0.1 m/px
    work, h, w, _ = choose_working_scale(
        2000, 2000, 0.05, target_m_per_px=0.1, tile=512, stride=384, max_windows=49
    )
    assert abs(work - 0.1) < 1e-9 and (h, w) == (1000, 1000)

    # whole 40 ha field (~632 m) at z18 (0.35 m/px ≈ 1806 px): the window budget is respected
    work, h, w, n = choose_working_scale(
        1806, 1806, 0.35, target_m_per_px=0.1, tile=512, stride=384, max_windows=49
    )
    assert n <= 49 and work >= 0.175
    assert work < 0.35  # still finer than what the frontend sent

    # no georeference: untouched
    assert choose_working_scale(300, 300, None, target_m_per_px=0.1, tile=512, stride=384, max_windows=49)[:3] == (
        None,
        300,
        300,
    )


def test_run_segformer_resamples_and_maps_back(monkeypatch):
    import sys
    import types

    import importlib.util

    import numpy as np

    spec = importlib.util.spec_from_file_location(
        "segmentation_service.schemas", ROOT / "app" / "segmentation_service" / "schemas.py"
    )
    schemas = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(schemas)
    seen = {}

    def fake_run_segmentation(rt, *, rgb=None, request=None, on_progress=None, **_kw):
        seen["shape"] = rgb.shape
        if on_progress:
            on_progress(1, 1)
        h, w = rgb.shape[:2]
        return schemas.SegmentResponse(
            navigable=schemas.PolygonPayload(polygon_px=[], area_px=0.0, valid=False),
            polygons=[
                schemas.PolygonItem(
                    polygon_px=[(0, 0), (w, 0), (w, h), (0, h)],
                    holes_px=[[(10, 10), (20, 10), (20, 20), (10, 20)]],
                    area_px=float(w * h),
                )
            ],
            image_hw=(h, w),
            checkpoint="x",
            metrics=schemas.SegmentMetrics(
                threshold_used=0.4, area_frac=1.0, prob_mean=0.5, prob_std=0.1,
                mode="prob_only", inference_ms=1.0, fp16=False, device="cpu",
            ),
        )

    fake_pipeline = types.ModuleType("segmentation_service.pipeline")
    fake_pipeline.run_segmentation = fake_run_segmentation
    monkeypatch.setitem(sys.modules, "segmentation_service", types.ModuleType("segmentation_service"))
    monkeypatch.setitem(sys.modules, "segmentation_service.pipeline", fake_pipeline)
    monkeypatch.setitem(sys.modules, "segmentation_service.schemas", schemas)

    class FakeSeg:
        meta = {"tile_size": 512}

        class settings:
            tile_size = 512
            sliding_stride = 384

    engine = ModelRuntime()
    engine._segformer = FakeSeg()
    progress = []
    image = np.zeros((300, 400, 3), dtype=np.uint8)  # 0.35 m/px → worked at 0.175 m/px (×2)
    payload = engine._run_segformer(image, 0.4, 0.35, lambda d, t: progress.append((d, t)))
    assert seen["shape"] == (600, 800, 3)
    assert progress == [(1, 1)]
    rings = payload["polygons"][0]["geometry"]["coordinates"]
    assert rings[0][2] == [400.0, 300.0]  # outer ring back in source pixels
    assert len(rings) == 2 and rings[1][1] == [10.0, 5.0]  # hole kept and scaled back
    assert abs(payload["info"]["work_m_per_px"] - 0.175) < 1e-9
    assert payload["info"]["work_size"] == [800, 600]


def test_run_yolo_works_at_training_scale():
    import numpy as np

    from app.ml_service.runtime import ModelRuntime

    names = {6: "water"}
    square = np.array([[10, 10], [60, 10], [60, 60], [10, 60]], dtype=float)

    class Boxes:
        cls = np.array([6])
        conf = np.array([0.9])

    class Masks:
        xy = [square]

    class Result:
        boxes = Boxes()
        masks = Masks()

    class FakeYolo:
        overrides = {"imgsz": 640}

        def __init__(self):
            self.names = names
            self.shapes = []

        def predict(self, image, conf, verbose, **kwargs):
            batch = image if isinstance(image, list) else [image]
            self.shapes.extend(crop.shape[:2] for crop in batch)
            return [Result() for _ in batch]

    engine = ModelRuntime()
    engine._yolo = FakeYolo()
    # 400×300 px at 0.35 m/px → ×2 upscale (0.175 m/px) = 800×600, one pass (≤ 1.5 tiles)
    payload = engine._run_yolo(np.zeros((300, 400, 3), dtype=np.uint8), 0.25, 0.35)
    assert engine._yolo.shapes == [(600, 800)]
    ring = payload["polygons"][0]["geometry"]["coordinates"][0]
    assert ring[0] == [5.0, 5.0] and ring[1] == [30.0, 5.0]  # back in source pixels
    assert payload["info"]["work_size"] == [800, 600]


def test_mask_to_polygons_keeps_forest_holes():
    import sys

    import numpy as np

    sys.path.insert(0, str(ROOT / "app"))
    from ml_core.polygon import mask_to_polygons

    mask = np.zeros((400, 400), dtype=np.uint8)
    mask[20:380, 20:380] = 1
    mask[150:250, 150:250] = 0  # forest island inside the field
    kept = mask_to_polygons(mask, min_area_px=500, simplify_tolerance=1.0, keep_holes=True)
    filled = mask_to_polygons(mask, min_area_px=500, simplify_tolerance=1.0)
    assert len(kept) == 1 and len(kept[0]["holes_px"]) == 1
    assert kept[0]["area_px"] < filled[0]["area_px"]
    assert "holes_px" not in filled[0]
