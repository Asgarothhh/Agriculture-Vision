"""Обучение YOLO26 на псевдоразметке tree/pole."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

from field_detecter.config_loader import load_config, project_root
from field_detecter.metrics import (
    compare_to_tz_targets,
    detection_f1,
    evaluate_detection_by_class,
    save_metrics_report,
)


def _yolo_model_name(weights: str) -> str:
    """YOLO26 при ultralytics>=26; иначе fallback YOLO11."""
    w = weights
    if "yolo26" in w:
        return w
    return w


def train_yolo(config: dict[str, Any]) -> Path:
    root = project_root()
    det_cfg = config["detection"]
    dataset_dir = root / det_cfg["dataset_dir"]
    data_yaml = dataset_dir / "data.yaml"
    if not data_yaml.exists():
        raise FileNotFoundError(
            f"Run pseudo_points first: missing {data_yaml}"
        )

    try:
        from ultralytics import YOLO
    except ImportError as e:
        raise SystemExit("pip install ultralytics") from e

    model_name = _yolo_model_name(det_cfg.get("model", "yolo26s.pt"))
    try:
        model = YOLO(model_name)
    except Exception:
        # Fallback if yolo26 weights unavailable in installed ultralytics
        fallback = "yolo11s.pt"
        print(f"Warning: {model_name} not found, using {fallback}")
        model = YOLO(fallback)

    out_dir = root / det_cfg["output_dir"]
    results = model.train(
        data=str(data_yaml),
        epochs=det_cfg.get("epochs", 80),
        imgsz=det_cfg.get("imgsz", 640),
        batch=det_cfg.get("batch", 16),
        project=str(out_dir.parent),
        name=out_dir.name,
        exist_ok=True,
    )
    best_weights = Path(results.save_dir) / "weights" / "best.pt"
    val_metrics = validate_yolo_pseudo(model, dataset_dir, config)
    report_path = root / config["metrics"]["report_path"]
    report: dict[str, Any] = {}
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
    report["detection"] = val_metrics
    tz = config.get("tz_targets", {})
    det_status = compare_to_tz_targets(
        {"f1_macro": val_metrics["f1_macro"]},
        targets={"f1_macro": tz.get("f1_macro", 0.80)},
    )
    report["detection_tz"] = det_status
    save_metrics_report(report_path, report)
    print(f"Detection metrics appended to {report_path}")
    return best_weights


def validate_yolo_pseudo(model, dataset_dir: Path, config: dict[str, Any]) -> dict[str, Any]:
    """Оценка F1 на val pseudo labels."""
    import cv2

    det_cfg = config["detection"]
    val_img_dir = dataset_dir / "images" / "val"
    val_lbl_dir = dataset_dir / "labels" / "val"
    match_dist = det_cfg.get("match_distance_px", 25)
    conf = det_cfg.get("conf", 0.25)

    f1_scores = []
    by_class_acc: dict[str, list[float]] = {"0": [], "1": []}

    for lbl_path in val_lbl_dir.glob("*.txt"):
        stem = lbl_path.stem
        img_path = val_img_dir / f"{stem}.jpg"
        if not img_path.exists():
            img_path = val_img_dir / f"{stem}.png"
        img = cv2.imread(str(img_path))
        if img is None:
            continue
        h, w = img.shape[:2]
        gt_boxes = []
        for line in lbl_path.read_text(encoding="utf-8").strip().splitlines():
            if not line.strip():
                continue
            parts = line.split()
            cls, xc, yc = int(parts[0]), float(parts[1]), float(parts[2])
            gt_boxes.append((xc * w, yc * h, cls))

        pred_boxes = []
        res = model.predict(str(img_path), conf=conf, verbose=False)[0]
        for box in res.boxes:
            xyxy = box.xyxy[0].cpu().numpy()
            cx = (xyxy[0] + xyxy[2]) / 2
            cy = (xyxy[1] + xyxy[3]) / 2
            cls = int(box.cls[0])
            pred_boxes.append((float(cx), float(cy), cls))

        m = detection_f1(pred_boxes, gt_boxes, match_dist_px=match_dist)
        f1_scores.append(m["f1"])
        bc = evaluate_detection_by_class(
            pred_boxes, gt_boxes, num_classes=2, match_dist_px=match_dist
        )
        for k, v in bc["per_class"].items():
            by_class_acc.setdefault(k, []).append(v["f1"])

    by_class = {
        k: {"f1": float(np.mean(v)) if v else 0.0}
        for k, v in by_class_acc.items()
    }
    f1_macro = float(np.mean(f1_scores)) if f1_scores else 0.0
    return {"per_class": by_class, "f1_macro": f1_macro, "n_val_images": len(f1_scores)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/agvision.yaml")
    args = parser.parse_args()
    cfg = load_config(args.config)
    train_yolo(cfg)


if __name__ == "__main__":
    main()
