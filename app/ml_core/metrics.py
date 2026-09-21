"""Метрики качества сегментации и детекции (ТЗ §5.1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np


def binary_mask_iou(pred: np.ndarray, gt: np.ndarray) -> float:
    pred = (pred > 0).astype(bool)
    gt = (gt > 0).astype(bool)
    inter = np.logical_and(pred, gt).sum()
    union = np.logical_or(pred, gt).sum()
    if union == 0:
        return 1.0 if inter == 0 else 0.0
    return float(inter / union)


def precision_recall(pred: np.ndarray, gt: np.ndarray) -> tuple[float, float]:
    pred = (pred > 0).astype(bool)
    gt = (gt > 0).astype(bool)
    tp = np.logical_and(pred, gt).sum()
    fp = np.logical_and(pred, ~gt).sum()
    fn = np.logical_and(~pred, gt).sum()
    precision = float(tp / (tp + fp)) if (tp + fp) > 0 else 0.0
    recall = float(tp / (tp + fn)) if (tp + fn) > 0 else 0.0
    return precision, recall


def evaluate_masks(
    pairs: list[tuple[np.ndarray, np.ndarray]],
) -> dict[str, float]:
    ious, precs, recs = [], [], []
    for pred, gt in pairs:
        ious.append(binary_mask_iou(pred, gt))
        p, r = precision_recall(pred, gt)
        precs.append(p)
        recs.append(r)
    return {
        "iou_mean": float(np.mean(ious)) if ious else 0.0,
        "precision_mean": float(np.mean(precs)) if precs else 0.0,
        "recall_mean": float(np.mean(recs)) if recs else 0.0,
        "n_samples": len(pairs),
    }


def evaluate_masks_masked(
    triples: list[tuple[np.ndarray, np.ndarray, np.ndarray]],
) -> dict[str, float]:
    """Метрики только на пикселях valid_mask > 0."""
    pairs = []
    for pred, gt, valid in triples:
        vm = valid.astype(bool)
        if not vm.any():
            continue
        pairs.append((pred[vm], gt[vm]))
    return evaluate_masks(pairs)


def detection_f1(
    pred_boxes: list[tuple[float, float, int]],
    gt_boxes: list[tuple[float, float, int]],
    *,
    match_dist_px: float = 25.0,
) -> dict[str, float]:
    """
    pred_boxes / gt_boxes: (cx, cy, class_id).
    Greedy matching по расстоянию centroid.
    """
    if not gt_boxes and not pred_boxes:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    if not gt_boxes:
        return {"precision": 0.0, "recall": 1.0, "f1": 0.0}
    if not pred_boxes:
        return {"precision": 1.0, "recall": 0.0, "f1": 0.0}

    matched_gt = set()
    tp = 0
    for px, py, pc in pred_boxes:
        best_j, best_d = -1, match_dist_px + 1
        for j, (gx, gy, gc) in enumerate(gt_boxes):
            if j in matched_gt or gc != pc:
                continue
            d = np.hypot(px - gx, py - gy)
            if d < best_d:
                best_d, best_j = d, j
        if best_j >= 0 and best_d <= match_dist_px:
            tp += 1
            matched_gt.add(best_j)
    fp = len(pred_boxes) - tp
    fn = len(gt_boxes) - tp
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    return {"precision": precision, "recall": recall, "f1": f1}


def evaluate_detection_by_class(
    pred_all: list[tuple[float, float, int]],
    gt_all: list[tuple[float, float, int]],
    num_classes: int = 2,
    *,
    match_dist_px: float = 25.0,
) -> dict[str, Any]:
    per_class = {}
    f1s = []
    for c in range(num_classes):
        pred_c = [b for b in pred_all if b[2] == c]
        gt_c = [b for b in gt_all if b[2] == c]
        m = detection_f1(pred_c, gt_c, match_dist_px=match_dist_px)
        per_class[str(c)] = m
        f1s.append(m["f1"])
    return {
        "per_class": per_class,
        "f1_macro": float(np.mean(f1s)) if f1s else 0.0,
    }


def compare_to_tz_targets(
    metrics: dict[str, float],
    *,
    targets: dict[str, float] | None = None,
) -> dict[str, Any]:
    if targets is None:
        targets = {
            "iou_mean": 0.90,
            "precision_mean": 0.90,
            "recall_mean": 0.95,
        }
    status = {
        k: {
            "value": metrics.get(k, 0.0),
            "target": targets[k],
            "passed": metrics.get(k, 0.0) >= targets[k],
        }
        for k in targets
        if k in ("iou_mean", "precision_mean", "recall_mean", "f1_macro")
    }
    return {"metrics": metrics, "tz_targets": status}


def save_metrics_report(path: Path, report: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
