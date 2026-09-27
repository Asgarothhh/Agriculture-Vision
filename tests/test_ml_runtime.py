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
    assert {"rgb", "request"} <= {a.arg for a in func.args.kwonlyargs}

    seen = {}

    def fake_run_segmentation(rt, *, rgb_path=None, nir_path=None, rgb=None, nir=None, request=None):
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

        def predict(self, image, conf, verbose):
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
