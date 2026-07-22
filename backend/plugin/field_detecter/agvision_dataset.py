"""Agriculture-Vision: 4 канала (NIR,R,G,B), boundary GT, valid mask."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import torch
from torch.utils.data import Dataset

FIELD_ID_RE = re.compile(r"^([A-Z0-9]+)_")


def parse_field_id(stem: str) -> str:
    m = FIELD_ID_RE.match(stem)
    return m.group(1) if m else stem.split("_")[0]


def discover_split_root(data_root: Path, version_dir: str, split: str) -> Path:
    """Ищет {root}/{version}/{split} или {root}/{split}."""
    candidates = [
        data_root / version_dir / split,
        data_root / split,
        data_root / f"{version_dir}-{split}",
    ]
    for p in candidates:
        if (p / "images" / "rgb").is_dir() or (p / "images" / "nir").is_dir():
            return p
    raise FileNotFoundError(
        f"Split '{split}' not found under {data_root}. "
        f"Tried: {[str(c) for c in candidates]}"
    )


def _resolve_label_path(split_root: Path, name: str, stem: str) -> Path | None:
    """Agriculture-Vision-2021: {split}/boundaries/, {split}/masks/."""
    for ext in (".png", ".jpg"):
        p = split_root / name / f"{stem}{ext}"
        if p.is_file():
            return p
    return None


def list_tile_stems(split_root: Path) -> list[str]:
    rgb_dir = split_root / "images" / "rgb"
    if not rgb_dir.is_dir():
        raise FileNotFoundError(f"Missing rgb dir: {rgb_dir}")
    stems = sorted(p.stem for p in rgb_dir.glob("*.png"))
    if not stems:
        stems = sorted(p.stem for p in rgb_dir.glob("*.jpg"))
    return stems


def load_agvision_tile(
    split_root: Path,
    stem: str,
    *,
    tile_size: int = 512,
) -> dict[str, Any]:
    rgb_path = split_root / "images" / "rgb" / f"{stem}.png"
    if not rgb_path.exists():
        rgb_path = split_root / "images" / "rgb" / f"{stem}.jpg"
    nir_path = split_root / "images" / "nir" / f"{stem}.png"
    if not nir_path.exists():
        nir_path = split_root / "images" / "nir" / f"{stem}.jpg"
    bnd_path = _resolve_label_path(split_root, "boundaries", stem)
    mask_path = _resolve_label_path(split_root, "masks", stem)

    rgb = cv2.cvtColor(cv2.imread(str(rgb_path)), cv2.COLOR_BGR2RGB)
    nir = cv2.imread(str(nir_path), cv2.IMREAD_GRAYSCALE)
    boundary = (
        cv2.imread(str(bnd_path), cv2.IMREAD_GRAYSCALE) if bnd_path else None
    )
    valid = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE) if mask_path else None

    if rgb is None:
        raise FileNotFoundError(f"Missing RGB for {stem}: {rgb_path}")
    if nir is None:
        raise FileNotFoundError(
            f"Missing NIR for {stem}: {nir_path} — обучение требует пару rgb+nir"
        )

    if boundary is None:
        boundary = np.zeros((tile_size, tile_size), dtype=np.uint8)
    if valid is None:
        valid = np.ones((tile_size, tile_size), dtype=np.uint8) * 255

    if rgb.shape[:2] != (tile_size, tile_size):
        rgb = cv2.resize(rgb, (tile_size, tile_size), interpolation=cv2.INTER_LINEAR)
    if nir.shape != (tile_size, tile_size):
        nir = cv2.resize(nir, (tile_size, tile_size), interpolation=cv2.INTER_LINEAR)
    if boundary.shape != (tile_size, tile_size):
        boundary = cv2.resize(boundary, (tile_size, tile_size), interpolation=cv2.INTER_NEAREST)
    if valid.shape != (tile_size, tile_size):
        valid = cv2.resize(valid, (tile_size, tile_size), interpolation=cv2.INTER_NEAREST)

    # NIR, R, G, B — как в статье Ag-Vision
    image_4ch = np.stack(
        [nir, rgb[..., 0], rgb[..., 1], rgb[..., 2]],
        axis=0,
    ).astype(np.float32)
    image_4ch /= 255.0

    gt_boundary = (boundary > 0).astype(np.uint8)
    valid_mask = (valid > 0).astype(np.uint8)

    return {
        "image": image_4ch,
        "boundary": gt_boundary,
        "valid_mask": valid_mask,
        "field_id": parse_field_id(stem),
        "stem": stem,
    }


class AgVisionDataset(Dataset):
    """PyTorch Dataset для Agriculture-Vision."""

    def __init__(
        self,
        data_root: str | Path,
        split: str = "train",
        *,
        version_dir: str = "Agriculture-Vision-2021",
        tile_size: int = 512,
        max_samples: int | None = None,
        transform=None,
        stems: list[str] | None = None,
    ) -> None:
        self.data_root = Path(data_root)
        self.split = split
        self.tile_size = tile_size
        self.transform = transform
        self.split_root = discover_split_root(self.data_root, version_dir, split)
        self.stems = stems if stems is not None else list_tile_stems(self.split_root)
        if max_samples is not None:
            self.stems = self.stems[: max_samples]

    def __len__(self) -> int:
        return len(self.stems)

    def __getitem__(self, idx: int) -> dict[str, Any]:
        stem = self.stems[idx]
        sample = load_agvision_tile(
            self.split_root, stem, tile_size=self.tile_size
        )
        if self.transform is not None:
            sample = self.transform(sample)
        sample["labels"] = sample["boundary"].astype(np.int64)
        return sample


def split_by_field_id(
    stems: list[str],
    split_root: Path,
    *,
    val_ratio: float = 0.15,
    seed: int = 42,
) -> tuple[list[str], list[str]]:
    """Группировка по field_id для детекции (без утечки)."""
    rng = np.random.default_rng(seed)
    field_to_stems: dict[str, list[str]] = {}
    for s in stems:
        fid = parse_field_id(s)
        field_to_stems.setdefault(fid, []).append(s)
    fields = sorted(field_to_stems.keys())
    rng.shuffle(fields)
    n_val = max(1, int(len(fields) * val_ratio))
    val_fields = set(fields[:n_val])
    train_stems, val_stems = [], []
    for fid, ss in field_to_stems.items():
        if fid in val_fields:
            val_stems.extend(ss)
        else:
            train_stems.extend(ss)
    return train_stems, val_stems


def collate_segformer_batch(batch: list[dict[str, Any]]) -> dict[str, torch.Tensor]:
    images = torch.stack([torch.from_numpy(b["image"]) for b in batch])
    labels = torch.stack([torch.from_numpy(b["labels"]) for b in batch])
    valid = torch.stack([torch.from_numpy(b["valid_mask"]) for b in batch])
    return {
        "pixel_values": images,
        "labels": labels,
        "valid_mask": valid,
    }
