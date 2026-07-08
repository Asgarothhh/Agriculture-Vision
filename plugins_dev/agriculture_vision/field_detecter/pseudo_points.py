"""Псевдоразметка деревьев и столбов на тайлах Agriculture-Vision."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from tqdm import tqdm

from field_detecter.agvision_dataset import (
    discover_split_root,
    list_tile_stems,
    load_agvision_tile,
    split_by_field_id,
)
from field_detecter.config_loader import load_config, project_root

CLASS_NAMES = ["tree", "pole"]


def ndvi(nir: np.ndarray, red: np.ndarray) -> np.ndarray:
    nir = nir.astype(np.float32)
    red = red.astype(np.float32)
    return (nir - red) / (nir + red + 1e-6)


def detect_trees(
    image_4ch: np.ndarray,
    boundary: np.ndarray,
    *,
    area_min: int = 50,
    area_max: int = 800,
) -> list[tuple[float, float, float, float, int]]:
    """YOLO bbox: x_center, y_center, w, h (normalized 0-1), class 0."""
    nir, r = image_4ch[0], image_4ch[1]
    nd = ndvi(nir * 255, r * 255)
    roi = boundary > 0
    if not roi.any():
        roi = np.ones_like(boundary, dtype=bool)
    nd = np.where(roi, nd, 0)
    nd_u8 = np.clip((nd + 0.2) * 127, 0, 255).astype(np.uint8)
    _, peaks = cv2.threshold(nd_u8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    peaks = cv2.bitwise_and(peaks, (roi.astype(np.uint8) * 255))
    num, labels, stats, centroids = cv2.connectedComponentsWithStats(peaks, connectivity=8)
    h, w = boundary.shape
    boxes = []
    for i in range(1, num):
        area = stats[i, cv2.CC_STAT_AREA]
        if area < area_min or area > area_max:
            continue
        cx, cy = centroids[i]
        bw = stats[i, cv2.CC_STAT_WIDTH]
        bh = stats[i, cv2.CC_STAT_HEIGHT]
        ar = max(bw, bh) / (min(bw, bh) + 1e-3)
        if ar > 4:
            continue
        boxes.append(
            (cx / w, cy / h, max(bw / w, 0.02), max(bh / h, 0.02), 0)
        )
    return boxes


def detect_poles(
    image_4ch: np.ndarray,
    boundary: np.ndarray,
    *,
    aspect_min: float = 3.0,
    width_max: int = 15,
) -> list[tuple[float, float, float, float, int]]:
    nir = (image_4ch[0] * 255).astype(np.uint8)
    roi = boundary > 0
    if not roi.any():
        roi = np.ones_like(boundary, dtype=bool)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 15))
    tophat = cv2.morphologyEx(nir, cv2.MORPH_TOPHAT, kernel)
    tophat = np.where(roi, tophat, 0)
    _, bin_img = cv2.threshold(tophat, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    num, labels, stats, centroids = cv2.connectedComponentsWithStats(bin_img, connectivity=8)
    h, w = boundary.shape
    boxes = []
    for i in range(1, num):
        bw = stats[i, cv2.CC_STAT_WIDTH]
        bh = stats[i, cv2.CC_STAT_HEIGHT]
        if bw > width_max and bh > width_max:
            continue
        ar = max(bw, bh) / (min(bw, bh) + 1e-3)
        if ar < aspect_min:
            continue
        cx, cy = centroids[i]
        boxes.append(
            (cx / w, cy / h, max(bw / w, 0.01), max(bh / h, 0.05), 1)
        )
    return boxes


def write_yolo_label(path: Path, boxes: list[tuple[float, float, float, float, int]]) -> None:
    lines = []
    for xc, yc, bw, bh, cls in boxes:
        lines.append(f"{cls} {xc:.6f} {yc:.6f} {bw:.6f} {bh:.6f}")
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def export_yolo_dataset(
    config: dict[str, Any],
    *,
    data_root: Path | None = None,
) -> Path:
    root = project_root()
    data_cfg = config["data"]
    pseudo_cfg = config["pseudo"]
    det_cfg = config["detection"]
    data_root = Path(data_root or root / data_cfg["root"])
    version_dir = data_cfg.get("version_dir", "Agriculture-Vision-2021")
    out_dir = root / det_cfg["dataset_dir"]
    if out_dir.exists():
        shutil.rmtree(out_dir)
    for sp in ("train", "val"):
        (out_dir / "images" / sp).mkdir(parents=True, exist_ok=True)
        (out_dir / "labels" / sp).mkdir(parents=True, exist_ok=True)

    split_root = discover_split_root(data_root, version_dir, "train")
    stems = list_tile_stems(split_root)
    if data_cfg.get("max_train_samples"):
        stems = stems[: data_cfg["max_train_samples"]]
    train_stems, val_stems = split_by_field_id(stems, split_root)

    yaml_path = out_dir / "data.yaml"
    yaml_path.write_text(
        f"path: {out_dir.resolve()}\n"
        f"train: images/train\n"
        f"val: images/val\n"
        f"names:\n  0: tree\n  1: pole\n",
        encoding="utf-8",
    )

    meta: dict[str, Any] = {"train": [], "val": []}

    for sp_name, stem_list in (("train", train_stems), ("val", val_stems)):
        for stem in tqdm(stem_list, desc=f"yolo {sp_name}"):
            sample = load_agvision_tile(split_root, stem)
            boxes = detect_trees(
                sample["image"],
                sample["boundary"],
                area_min=pseudo_cfg.get("tree_area_min", 50),
                area_max=pseudo_cfg.get("tree_area_max", 800),
            )
            boxes += detect_poles(
                sample["image"],
                sample["boundary"],
                aspect_min=pseudo_cfg.get("pole_aspect_min", 3.0),
                width_max=pseudo_cfg.get("pole_width_max", 15),
            )
            # RGB preview for YOLO (3 ch)
            rgb = np.stack(
                [
                    sample["image"][1],
                    sample["image"][2],
                    sample["image"][3],
                ],
                axis=-1,
            )
            rgb_u8 = (rgb * 255).astype(np.uint8)
            img_out = out_dir / "images" / sp_name / f"{stem}.jpg"
            cv2.imwrite(str(img_out), cv2.cvtColor(rgb_u8, cv2.COLOR_RGB2BGR))
            lbl_out = out_dir / "labels" / sp_name / f"{stem}.txt"
            write_yolo_label(lbl_out, boxes)
            meta[sp_name].append({"stem": stem, "n_boxes": len(boxes)})

    (out_dir / "pseudo_meta.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )
    print(f"YOLO dataset: {out_dir}")
    return out_dir


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/agvision.yaml")
    parser.add_argument("--data-root", default=None)
    args = parser.parse_args()
    cfg = load_config(args.config)
    export_yolo_dataset(cfg, data_root=Path(args.data_root) if args.data_root else None)


if __name__ == "__main__":
    main()
