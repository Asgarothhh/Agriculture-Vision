#!/usr/bin/env python3
"""Pack an unzipped PyTorch checkpoint into config/segformer_best.pt.

torch.save stores records under a subdirectory named after the file stem
(e.g. segformer_best/data.pkl). If someone unzipped best_iou.pth into
config/segformer_best/best_iou/, this script rebuilds a loadable .pt.
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SRC = ROOT / "config" / "segformer_best" / "best_iou"
DEFAULT_DST = ROOT / "config" / "segformer_best.pt"


def pack(src: Path, dst: Path) -> Path:
    if not src.is_dir():
        raise SystemExit(
            f"Source directory not found: {src}\n"
            "Expected unzipped checkpoint contents (data.pkl, data/, …)."
        )
    pkl = src / "data.pkl"
    if not pkl.is_file():
        raise SystemExit(f"Missing {pkl} — not a PyTorch checkpoint directory")

    dst.parent.mkdir(parents=True, exist_ok=True)
    prefix = dst.stem
    with zipfile.ZipFile(dst, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        for path in sorted(src.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(src).as_posix()
            if rel.startswith(".data/"):
                continue
            info = zipfile.ZipInfo(f"{prefix}/{rel}")
            info.compress_type = zipfile.ZIP_STORED
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.create_system = 0
            info.flag_bits = 0
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())

    try:
        import torch
    except ImportError as exc:
        dst.unlink(missing_ok=True)
        raise SystemExit("torch is required to verify the packed checkpoint") from exc

    ckpt = torch.load(dst, map_location="cpu", weights_only=False)
    if not isinstance(ckpt, dict) or "model_state" not in ckpt:
        dst.unlink(missing_ok=True)
        raise SystemExit("Packed file is not a SegFormer checkpoint (missing model_state)")
    print(f"Wrote {dst} ({dst.stat().st_size} bytes)")
    return dst


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path, default=DEFAULT_SRC)
    parser.add_argument("--dst", type=Path, default=DEFAULT_DST)
    args = parser.parse_args()
    pack(args.src, args.dst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
