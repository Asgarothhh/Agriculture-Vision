
"""Скачивание Agriculture-Vision с Hugging Face и распаковка."""

from __future__ import annotations

import argparse
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Download Agriculture-Vision")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=ROOT / "data" / "agvision",
        help="Каталог для данных",
    )
    parser.add_argument(
        "--extract",
        action="store_true",
        help="Распаковать tar.gz после скачивания",
    )
    parser.add_argument(
        "--repo",
        default="shi-labs/Agriculture-Vision",
        help="HF dataset repo",
    )
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    try:
        from huggingface_hub import hf_hub_download
    except ImportError as e:
        raise SystemExit("pip install huggingface_hub") from e

    print(f"Downloading {args.repo} (tar.gz, ~21 GB)...")
    archive = hf_hub_download(
        repo_id=args.repo,
        filename="Agriculture-Vision-2021.tar.gz",
        repo_type="dataset",
        local_dir=str(args.out_dir),
    )
    archive_path = Path(archive)
    print(f"Saved: {archive_path}")

    if args.extract:
        print("Extracting...")
        with tarfile.open(archive_path, "r:gz") as tf:
            tf.extractall(path=args.out_dir)
        print(f"Extracted to {args.out_dir}")
        expected = args.out_dir / "Agriculture-Vision-2021" / "train" / "images" / "rgb"
        if expected.is_dir():
            print(f"OK: {expected}")
        else:
            print(
                "Warning: expected Agriculture-Vision-2021/train/images/rgb — "
                "check archive layout."
            )


if __name__ == "__main__":
    main()
