"""Аугментации Ag-Vision: 4ch NIR+RGB, устойчивость к шуму, опора на NIR."""

from __future__ import annotations

import random
from typing import Any

import albumentations as A
import cv2
import numpy as np


def _chw_to_hwc4(image_4ch: np.ndarray) -> np.ndarray:
    return np.transpose(image_4ch, (1, 2, 0)).astype(np.float32)


def _hwc4_to_chw(img: np.ndarray) -> np.ndarray:
    return np.transpose(img, (2, 0, 1)).astype(np.float32)


class AgVisionTrainAugment:
    """
    Геометрия — на 4 канала и маски синхронно.
    Фотометрия — RGB и NIR отдельно; случайное «выключение» RGB → модель опирается на NIR.
    """

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        cfg = cfg or {}
        self.p_noise = cfg.get("p_noise", 0.45)
        self.p_blur = cfg.get("p_blur", 0.35)
        self.p_brightness = cfg.get("p_brightness", 0.5)
        self.p_rgb_dropout = cfg.get("p_rgb_dropout", 0.12)
        self.p_nir_noise = cfg.get("p_nir_noise", 0.4)
        self.noise_std_rgb = cfg.get("noise_std_rgb", 0.04)
        self.noise_std_nir = cfg.get("noise_std_nir", 0.03)
        self.nir_gain = tuple(cfg.get("nir_gain", (0.85, 1.15)))

        self.geo = A.Compose(
            [
                A.HorizontalFlip(p=0.5),
                A.VerticalFlip(p=0.5),
                A.RandomRotate90(p=0.5),
                A.ShiftScaleRotate(
                    shift_limit=0.06,
                    scale_limit=0.12,
                    rotate_limit=20,
                    border_mode=cv2.BORDER_REFLECT_101,
                    p=0.45,
                ),
            ],
            additional_targets={
                "boundary": "mask",
                "valid_mask": "mask",
            },
        )

    def _photometric(self, img4: np.ndarray) -> np.ndarray:
        nir = img4[..., 0].copy()
        rgb = img4[..., 1:4].copy()

        if random.random() < self.p_brightness:
            rgb = np.clip(
                rgb * random.uniform(0.82, 1.18) + random.uniform(-0.06, 0.06),
                0,
                1,
            )
        if random.random() < self.p_nir_noise:
            gain = random.uniform(*self.nir_gain)
            nir = np.clip(nir * gain + random.uniform(-0.05, 0.05), 0, 1)

        if random.random() < self.p_noise:
            std = self.noise_std_rgb * random.uniform(0.6, 1.4)
            rgb = np.clip(
                rgb + np.random.normal(0, std, rgb.shape).astype(np.float32), 0, 1
            )
        if random.random() < self.p_nir_noise:
            std = self.noise_std_nir * random.uniform(0.6, 1.4)
            nir = np.clip(
                nir + np.random.normal(0, std, nir.shape).astype(np.float32), 0, 1
            )

        if random.random() < self.p_blur:
            k = random.choice([3, 5])
            rgb = cv2.GaussianBlur(rgb, (k, k), random.uniform(0.4, 1.2))
            if random.random() < 0.5:
                nir_u8 = (nir * 255).astype(np.uint8)
                nir = cv2.GaussianBlur(nir_u8, (k, k), random.uniform(0.4, 1.0)).astype(
                    np.float32
                ) / 255.0

        if random.random() < self.p_rgb_dropout:
            rgb[:] = 0.0

        out = np.zeros_like(img4)
        out[..., 0] = nir
        out[..., 1:4] = rgb
        return out

    def __call__(self, sample: dict[str, Any]) -> dict[str, Any]:
        img4 = _chw_to_hwc4(sample["image"])
        boundary = sample["boundary"].astype(np.uint8)
        valid = sample["valid_mask"].astype(np.uint8)
        out = self.geo(image=img4, boundary=boundary, valid_mask=valid)
        img4 = self._photometric(out["image"])
        sample["image"] = _hwc4_to_chw(img4)
        sample["boundary"] = out["boundary"]
        sample["valid_mask"] = out["valid_mask"]
        return sample


def build_train_transform(aug_cfg: dict[str, Any] | None) -> AgVisionTrainAugment | None:
    if not aug_cfg or not aug_cfg.get("enabled", True):
        return None
    return AgVisionTrainAugment(aug_cfg)
