"""FP16-совместимый forward поверх SegFormer"""

from __future__ import annotations

import numpy as np
import torch
import torch.nn.functional as F

from field_detecter.seg_infer import _TTA_FLIPS, _apply_tta_flip
from field_detecter.train_seg import Segformer4ChWrapper


@torch.no_grad()
def predict_prob(
    model: Segformer4ChWrapper,
    image_4ch: np.ndarray,
    device: torch.device,
    *,
    tta: bool = True,
    fp16: bool = False,
) -> np.ndarray:
    """Вероятность класса boundary, H×W float32."""
    x = torch.from_numpy(image_4ch).unsqueeze(0).to(device)
    use_amp = fp16 and device.type == "cuda"
    dtype = torch.float16 if use_amp else torch.float32

    def _forward(xi: torch.Tensor) -> torch.Tensor:
        if use_amp:
            xi = xi.to(dtype=dtype)
        if use_amp:
            with torch.autocast(device_type="cuda", dtype=torch.float16):
                logits = model(xi).logits
        else:
            logits = model(xi).logits
        if logits.shape[-2:] != xi.shape[-2:]:
            logits = F.interpolate(
                logits.float(),
                size=xi.shape[-2:],
                mode="bilinear",
                align_corners=False,
            )
        else:
            logits = logits.float()
        return logits

    if tta:
        probs = []
        for flip in _TTA_FLIPS:
            xi = _apply_tta_flip(x, flip)
            logits = _forward(xi)
            logits = _apply_tta_flip(logits, flip)
            probs.append(logits.softmax(dim=1)[:, 1])
        prob = torch.stack(probs).mean(0)[0].cpu().numpy()
    else:
        logits = _forward(x)
        prob = logits.softmax(dim=1)[0, 1].cpu().numpy()
    return prob.astype(np.float32)


def _tile_starts(size: int, tile: int, stride: int) -> list[int]:
    """Начала окон с гарантированным покрытием правого/нижнего края."""
    if size <= tile:
        return [0]
    starts = list(range(0, size - tile + 1, max(1, stride)))
    if starts[-1] != size - tile:
        starts.append(size - tile)
    return starts


def _tile_window(tile: int) -> np.ndarray:
    """Окно, спадающее к краям тайла — иначе на стыках видны швы."""
    ramp = np.hanning(tile).astype(np.float32)
    ramp = np.clip(ramp, 0.05, None)
    return np.outer(ramp, ramp)


@torch.no_grad()
def predict_prob_sliding(
    model: Segformer4ChWrapper,
    image_4ch: np.ndarray,
    device: torch.device,
    *,
    tile: int = 512,
    stride: int = 256,
    tta: bool = False,
    fp16: bool = False,
) -> np.ndarray:
    """Вероятность поля для большой сцены в нативном разрешении (4ch CHW)."""
    _, h, w = image_4ch.shape
    if h <= tile and w <= tile:
        return predict_prob(model, image_4ch, device, tta=tta, fp16=fp16)

    prob_acc = np.zeros((h, w), dtype=np.float32)
    weight = np.zeros((h, w), dtype=np.float32)
    window = _tile_window(tile)
    for y0 in _tile_starts(h, tile, stride):
        for x0 in _tile_starts(w, tile, stride):
            y1, x1 = min(y0 + tile, h), min(x0 + tile, w)
            ph, pw = y1 - y0, x1 - x0
            patch = np.zeros((4, tile, tile), dtype=np.float32)
            patch[:, :ph, :pw] = image_4ch[:, y0:y1, x0:x1]
            p = predict_prob(model, patch, device, tta=tta, fp16=fp16)[:ph, :pw]
            wgt = window[:ph, :pw]
            prob_acc[y0:y1, x0:x1] += p * wgt
            weight[y0:y1, x0:x1] += wgt
    return prob_acc / np.maximum(weight, 1e-6)


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
    fp16: bool = False,
) -> np.ndarray:
    from field_detecter.seg_infer import prob_to_mask

    prob = predict_prob_sliding(
        model, image_4ch, device, tile=tile, stride=stride, tta=tta, fp16=fp16
    )
    mask, _, _ = prob_to_mask(prob, threshold)
    return mask
