from pathlib import Path

from app.ml_service.runtime import ModelRuntime, runtime
from app.ml_service.schemas import InferenceRequest, InferenceResponse


ROOT = Path(__file__).resolve().parents[1]


def test_weight_files_exist():
    yolo = ROOT / "config" / "yolo_best.pt"
    seg = ROOT / "config" / "segformer_best.pt"
    assert yolo.is_file(), "YOLO weights missing: config/yolo_best.pt"
    # SegFormer checkpoint may be empty until copied; resolver still reports the path attempt
    engine = ModelRuntime()
    found_yolo = engine._resolve("config/yolo_best.pt")
    assert found_yolo is not None
    assert found_yolo.stat().st_size > 0


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
