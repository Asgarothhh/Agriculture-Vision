"""Инференс SegFormer: загрузка изображения → маска → полигоны."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np
import torch
import torch.nn.functional as F

from field_detecter.train_seg import Segformer4ChWrapper

# TTA flip по H,W для NCHW: () = без отражения
_TTA_FLIPS: tuple[tuple[int, ...], ...] = ((), (2,), (3,), (2, 3))


def _apply_tta_flip(x: torch.Tensor, dims: tuple[int, ...]) -> torch.Tensor:
    return x if not dims else x.flip(dims)


def load_segformer_checkpoint(
    ckpt_path: str | Path,
    *,
    device: str | torch.device | None = None,
) -> tuple[Segformer4ChWrapper, dict[str, Any]]:
    ckpt_path = Path(ckpt_path)
    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    device = torch.device(device)
    ckpt = torch.load(ckpt_path, map_location=device, weights_only=False)
    cfg = ckpt.get("config", {})
    seg_cfg = cfg.get("segmentation", {})
    model_id = seg_cfg.get("model_id", "nvidia/segformer-b4-finetuned-ade-512-512")
    model = Segformer4ChWrapper(model_id, num_labels=seg_cfg.get("num_labels", 2))
    model.load_state_dict(ckpt["model_state"])
    model.to(device)
    model.eval()
    meta = {
        "epoch": ckpt.get("epoch"),
        "val_metrics": ckpt.get("val_metrics"),
        "threshold": seg_cfg.get("val_threshold", 0.5),
        "tile_size": cfg.get("data", {}).get("tile_size", 512),
    }
    return model, meta


def letterbox_image(
    rgb: np.ndarray,
    nir: np.ndarray | None,
    tile_size: int,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Вписать в tile_size×tile_size без искажения пропорций (чёрный padding)."""
    h, w = rgb.shape[:2]
    scale = min(tile_size / w, tile_size / h)
    nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    rgb_lb = cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_LINEAR)
    canvas = np.zeros((tile_size, tile_size, 3), dtype=rgb.dtype)
    canvas[:nh, :nw] = rgb_lb
    if nir is None:
        nir = rgb[..., 0]
    nir_lb = cv2.resize(nir, (nw, nh), interpolation=cv2.INTER_LINEAR)
    nir_canvas = np.zeros((tile_size, tile_size), dtype=nir.dtype)
    nir_canvas[:nh, :nw] = nir_lb
    meta = {
        "orig_hw": (h, w),
        "scale": scale,
        "content_nw": nw,
        "content_nh": nh,
        "tile_size": tile_size,
    }
    return canvas, nir_canvas, meta


def crop_mask_from_letterbox(mask: np.ndarray, meta: dict[str, Any]) -> np.ndarray:
    """Обрезать padding и вернуть маску в исходном разрешении."""
    nh, nw = meta["content_nh"], meta["content_nw"]
    cropped = mask[:nh, :nw]
    h0, w0 = meta["orig_hw"]
    if cropped.shape != (h0, w0):
        cropped = cv2.resize(cropped, (w0, h0), interpolation=cv2.INTER_NEAREST)
    return cropped


def load_rgb_nir(
    rgb_path: str | Path,
    nir_path: str | Path | None = None,
    *,
    tile_size: int | None = None,
    letterbox: bool = True,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any] | None]:
    """
    RGB uint8 H×W×3 и 4ch float NIR,R,G,B [0,1] CHW.
    Если NIR нет — дублируется R-канал.
    letterbox=True — без растягивания до квадрата (рекомендуется для своих снимков).
    """
    rgb_path = Path(rgb_path)
    bgr = cv2.imread(str(rgb_path))
    if bgr is None:
        raise FileNotFoundError(rgb_path)
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    meta: dict[str, Any] | None = None

    nir: np.ndarray | None = None
    if nir_path and Path(nir_path).is_file():
        nir = cv2.imread(str(nir_path), cv2.IMREAD_GRAYSCALE)

    if tile_size:
        if letterbox:
            rgb, nir_arr, meta = letterbox_image(rgb, nir, tile_size)
            nir = nir_arr
        else:
            rgb = cv2.resize(rgb, (tile_size, tile_size), interpolation=cv2.INTER_LINEAR)
            if nir is not None:
                nir = cv2.resize(nir, (tile_size, tile_size), interpolation=cv2.INTER_LINEAR)

    if nir is None:
        nir = rgb[..., 0].copy()

    image_4ch = np.stack([nir, rgb[..., 0], rgb[..., 1], rgb[..., 2]], axis=0).astype(
        np.float32
    )
    image_4ch /= 255.0
    return rgb, image_4ch, meta


def excess_green(rgb: np.ndarray) -> np.ndarray:
    """ExG индекс вегетации [0,1] из RGB uint8."""
    r = rgb[..., 0].astype(np.float32)
    g = rgb[..., 1].astype(np.float32)
    b = rgb[..., 2].astype(np.float32)
    exg = 2.0 * g - r - b
    lo, hi = float(exg.min()), float(exg.max())
    if hi - lo < 1e-6:
        return np.zeros_like(exg)
    return (exg - lo) / (hi - lo)


def _edge_density(gray: np.ndarray, sigma: float = 8.0) -> np.ndarray:
    edges = cv2.Canny(gray, 60, 160)
    ed = edges.astype(np.float32) / 255.0
    return cv2.GaussianBlur(ed, (0, 0), sigma)


def _prob_is_saturated(prob: np.ndarray, std_thr: float = 0.06, range_thr: float = 0.12) -> bool:
    return float(prob.std()) < std_thr or float(prob.max() - prob.min()) < range_thr


def _field_score_map(rgb: np.ndarray) -> np.ndarray:
    """Карта «похожести на поле» по RGB (без NN). Учитывает голое и зелёное поле."""
    gray_u8 = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    gray = gray_u8.astype(np.float32) / 255.0
    texture = cv2.GaussianBlur(
        np.abs(cv2.Laplacian(gray, cv2.CV_32F)), (0, 0), 9
    )
    texture_n = texture / (float(texture.max()) + 1e-6)
    edges = _edge_density(gray_u8, sigma=10.0)
    exg = excess_green(rgb)
    smooth_open = (1.0 - texture_n) * (1.0 - edges)
    # не штрафуем «голое» поле низким ExG
    score = 0.72 * smooth_open + 0.28 * (smooth_open * exg)
    h, w = score.shape
    yy, xx = np.ogrid[:h, :w]
    cy, cx = (h - 1) / 2.0, (w - 1) / 2.0
    dist = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)
    dist = dist / (dist.max() + 1e-6)
    score = score * (1.0 - 0.18 * dist)
    return (score - score.min()) / (score.max() - score.min() + 1e-6)


def _pick_field_component(
    score: np.ndarray,
    *,
    max_area_frac: float = 0.55,
    min_area_frac: float = 0.04,
) -> tuple[np.ndarray, float]:
    """Выбор компоненты: площадь + близость к центру кадра."""
    h, w = score.shape
    img_area = h * w
    cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
    best_mask: np.ndarray | None = None
    best_metric = -1.0
    best_th = 0.5

    for q in (0.28, 0.32, 0.36, 0.40, 0.45, 0.50):
        th = float(np.quantile(score, q))
        m = (score >= th).astype(np.uint8)
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k)
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, k)
        n, labels, stats, centroids = cv2.connectedComponentsWithStats(m, connectivity=8)
        for i in range(1, n):
            area = int(stats[i, cv2.CC_STAT_AREA])
            if area < min_area_frac * img_area or area > max_area_frac * img_area:
                continue
            cxi, cyi = centroids[i]
            dist = np.hypot(cxi - cx, cyi - cy) / np.hypot(cx, cy)
            centrality = 1.0 - min(float(dist), 1.0)
            metric = area * (0.65 + 0.35 * centrality)
            if metric > best_metric:
                best_metric = metric
                best_th = th
                best_mask = (labels == i).astype(np.uint8)

    if best_mask is None:
        th = float(np.quantile(score, 0.32))
        best_mask = (score >= th).astype(np.uint8)
        n, labels, stats, _ = cv2.connectedComponentsWithStats(best_mask, connectivity=8)
        if n > 1:
            i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
            best_mask = (labels == i).astype(np.uint8)
        best_th = th

    return best_mask, best_th


def _mask_from_rgb_heuristic(
    rgb: np.ndarray,
    *,
    max_area_frac: float = 0.55,
) -> tuple[np.ndarray, np.ndarray, dict[str, float]]:
    """Fallback при prob≈const: маска по текстуре/границам + выбор крупного поля у центра."""
    score = _field_score_map(rgb)
    mask, th = _pick_field_component(score, max_area_frac=max_area_frac)
    return mask, score, {
        "mode": "rgb_heuristic",
        "score_th": th,
        "area_frac": float(mask.mean()),
    }


def prob_to_mask(
    prob: np.ndarray,
    threshold: float = 0.5,
    *,
    rgb_uint8: np.ndarray | None = None,
    max_area_frac: float = 0.65,
    keep_largest: bool = True,
    morph_open: int = 5,
    auto_raise_threshold: bool = True,
) -> tuple[np.ndarray, float, dict[str, float]]:
    """
    Вероятность → бинарная маска поля.

  На снимках вне Ag-Vision prob часто «залипает» около 1.0 — тогда используется
    комбинация ExG + низких границ (поле vs застройка).
    """
    if rgb_uint8 is not None and _prob_is_saturated(prob):
        mask, score_map, hinfo = _mask_from_rgb_heuristic(
            rgb_uint8, max_area_frac=max_area_frac
        )
        info = {
            "threshold_used": hinfo["score_th"],
            "area_frac": hinfo["area_frac"],
            "prob_mean": float(prob.mean()),
            "prob_std": float(prob.std()),
            "prob_max": float(prob.max()),
            "mode": "saturated_fallback",
            "score_map": score_map,
        }
        return mask, hinfo["score_th"], info

    th = float(threshold)
    score = prob.copy()
    if rgb_uint8 is not None:
        exg = excess_green(rgb_uint8)
        edges = _edge_density(cv2.cvtColor(rgb_uint8, cv2.COLOR_RGB2GRAY))
        score = 0.55 * prob + 0.30 * exg + 0.15 * (1.0 - edges)
        score = (score - score.min()) / (score.max() - score.min() + 1e-6)
        th = float(np.quantile(score, 0.70))

    mask = (score >= th).astype(np.uint8)

    if auto_raise_threshold:
        while mask.mean() > max_area_frac and th < 0.98:
            th = min(th + 0.03, 0.98)
            mask = (score >= th).astype(np.uint8)

    if morph_open > 0:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (morph_open, morph_open))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)

    if keep_largest and mask.any():
        n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        if n > 1:
            largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
            mask = (labels == largest).astype(np.uint8)

    info = {
        "threshold_used": th,
        "area_frac": float(mask.mean()),
        "prob_mean": float(prob.mean()),
        "prob_std": float(prob.std()),
        "prob_max": float(prob.max()),
        "prob_p90": float(np.quantile(prob, 0.9)),
        "mode": "prob_combined" if rgb_uint8 is not None else "prob_only",
        "score_map": score,
    }
    return mask, th, info


@torch.no_grad()
def predict_prob(
    model: Segformer4ChWrapper,
    image_4ch: np.ndarray,
    device: torch.device,
    *,
    tta: bool = True,
) -> np.ndarray:
    """Вероятность класса boundary, H×W float32."""
    x = torch.from_numpy(image_4ch).unsqueeze(0).to(device)
    if tta:
        probs = []
        for flip in _TTA_FLIPS:
            xi = _apply_tta_flip(x, flip)
            logits = model(xi).logits
            if logits.shape[-2:] != xi.shape[-2:]:
                logits = F.interpolate(
                    logits, size=xi.shape[-2:], mode="bilinear", align_corners=False
                )
            logits = _apply_tta_flip(logits, flip)
            probs.append(logits.softmax(dim=1)[:, 1])
        prob = torch.stack(probs).mean(0)[0].cpu().numpy()
    else:
        logits = model(x).logits
        if logits.shape[-2:] != x.shape[-2:]:
            logits = F.interpolate(
                logits, size=x.shape[-2:], mode="bilinear", align_corners=False
            )
        prob = logits.softmax(dim=1)[0, 1].cpu().numpy()
    return prob


@torch.no_grad()
def predict_mask_sliding(
    model: Segformer4ChWrapper,
    image_4ch: np.ndarray,
    device: torch.device,
    *,
    tile: int = 512,
    stride: int = 256,
    threshold: float = 0.5,
    tta: bool = False,
) -> np.ndarray:
    """Sliding window для больших сцен (4ch CHW)."""
    _, h, w = image_4ch.shape
    if h <= tile and w <= tile:
        prob = predict_prob(model, image_4ch, device, tta=tta)
        mask, _, _ = prob_to_mask(prob, threshold)
        return mask

    prob_acc = np.zeros((h, w), dtype=np.float32)
    weight = np.zeros((h, w), dtype=np.float32)
    for y0 in range(0, max(h - tile + 1, 1), stride):
        for x0 in range(0, max(w - tile + 1, 1), stride):
            y1, x1 = min(y0 + tile, h), min(x0 + tile, w)
            patch = np.zeros((4, tile, tile), dtype=np.float32)
            ph, pw = y1 - y0, x1 - x0
            patch[:, :ph, :pw] = image_4ch[:, y0:y1, x0:x1]
            p = predict_prob(model, patch, device, tta=tta)[:ph, :pw]
            prob_acc[y0:y1, x0:x1] += p
            weight[y0:y1, x0:x1] += 1.0
    prob = prob_acc / np.maximum(weight, 1e-6)
    mask, _, _ = prob_to_mask(prob, threshold)
    return mask


def predict_field_mask(
    model: Segformer4ChWrapper,
    image_4ch: np.ndarray,
    device: torch.device,
    *,
    threshold: float = 0.5,
    tta: bool = True,
    letterbox_meta: dict[str, Any] | None = None,
    rgb_uint8: np.ndarray | None = None,
    **mask_kw: Any,
) -> tuple[np.ndarray, np.ndarray, float, dict[str, float]]:
    """prob H×W, mask H×W (в координатах image_4ch), mask на исходном кадре если meta задан."""
    prob = predict_prob(model, image_4ch, device, tta=tta)
    mask, th_used, info = prob_to_mask(
        prob, threshold, rgb_uint8=rgb_uint8, **mask_kw
    )
    score_map = info.get("score_map", prob)
    if letterbox_meta is not None:
        prob_out = crop_mask_from_letterbox(prob, letterbox_meta)
        mask_out = crop_mask_from_letterbox(mask, letterbox_meta)
        score_out = crop_mask_from_letterbox(score_map, letterbox_meta)
        info["score_map"] = score_out
        return prob_out, mask_out, th_used, info
    info["score_map"] = score_map
    return prob, mask, th_used, info


def load_rgb_nir_from_array(
    rgb: np.ndarray,
    nir: np.ndarray | None = None,
) -> np.ndarray:
    """RGB H×W×3 uint8 → 4ch float CHW."""
    if nir is None:
        nir = rgb[..., 0]
    image_4ch = np.stack([nir, rgb[..., 0], rgb[..., 1], rgb[..., 2]], axis=0).astype(
        np.float32
    )
    return image_4ch / 255.0
