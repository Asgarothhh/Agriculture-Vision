"""CLI: проверка чекпоинта и прогон на файле."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from model.pipeline import run_segmentation
from model.runtime import SegmentationRuntime
from model.schemas import SegmentRequest
from model.settings import load_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Field segmentation inference (FP16)")
    parser.add_argument("--rgb", type=Path, required=True, help="RGB image path")
    parser.add_argument("--nir", type=Path, default=None, help="Optional NIR path")
    parser.add_argument("--checkpoint", type=Path, default=None)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--tta", action="store_true")
    parser.add_argument("--sliding", action="store_true")
    parser.add_argument("--mask-png", action="store_true")
    parser.add_argument("--out", type=Path, default=None, help="Write JSON result here")
    args = parser.parse_args(argv)

    settings = load_settings(args.config)
    if args.checkpoint:
        settings.checkpoint_path = args.checkpoint

    runtime = SegmentationRuntime(settings)
    runtime.load()

    req = SegmentRequest(
        tta=True if args.tta else None,
        use_sliding=args.sliding,
        include_mask_png=args.mask_png,
    )
    result = run_segmentation(
        runtime,
        rgb_path=args.rgb,
        nir_path=args.nir,
        request=req,
    )
    payload = result.model_dump()
    if not args.mask_png:
        payload.pop("mask_png_base64", None)

    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"Wrote {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
