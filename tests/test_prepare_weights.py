from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "prepare-weights.sh"


def _run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    merged.update(env)
    return subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=ROOT,
        env=merged,
        check=False,
        capture_output=True,
        text=True,
    )


def test_prepare_weights_copies_yolo_alias(tmp_path: Path) -> None:
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    src.mkdir()
    dest.mkdir()
    (src / "yolo.pt").write_bytes(b"yolo-weights")
    (src / "segformer_best.pt").write_bytes(b"segformer-weights")

    result = _run(
        {
            "WEIGHTS_DIR": str(src),
            "WEIGHTS_DEST": str(dest),
            "WEIGHTS_ONLY": "1",
        }
    )

    assert result.returncode == 0, result.stderr
    assert (dest / "yolo_best.pt").read_bytes() == b"yolo-weights"
    assert (dest / "segformer_best.pt").read_bytes() == b"segformer-weights"


def test_prepare_weights_fails_when_yolo_missing(tmp_path: Path) -> None:
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    src.mkdir()
    dest.mkdir()
    (src / "segformer_best.pt").write_bytes(b"segformer-weights")

    result = _run(
        {
            "WEIGHTS_DIR": str(src),
            "WEIGHTS_DEST": str(dest),
            "WEIGHTS_ONLY": "1",
        }
    )

    assert result.returncode == 1
    assert "MISSING yolo_best.pt" in result.stderr
    assert "listing" in result.stderr
