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
