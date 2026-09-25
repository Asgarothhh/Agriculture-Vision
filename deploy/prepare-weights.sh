#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/config"
mkdir -p "$DEST"

candidates=()
if [ -n "${WEIGHTS_DIR:-}" ]; then
  candidates+=("$WEIGHTS_DIR")
fi
candidates+=(
  "$DEST"
  "/var/agriculture-vision/config"
  "/opt/agriculture-vision/config"
  "${HOME:-/root}/agriculture-vision/config"
)

copy_one() {
  local name="$1"
  if [ -f "$DEST/$name" ] && [ -s "$DEST/$name" ]; then
    echo "weights: using $DEST/$name ($(du -h "$DEST/$name" | cut -f1))"
    return 0
  fi
  local src
  for dir in "${candidates[@]}"; do
    src="$dir/$name"
    if [ "$src" = "$DEST/$name" ]; then
      continue
    fi
    if [ -f "$src" ] && [ -s "$src" ]; then
      cp -a "$src" "$DEST/$name"
      echo "weights: copied $src -> $DEST/$name ($(du -h "$DEST/$name" | cut -f1))"
      return 0
    fi
  done
  return 1
}

missing=0
if ! copy_one "yolo_best.pt"; then
  echo "weights: MISSING yolo_best.pt" >&2
  missing=1
fi
if ! copy_one "segformer_best.pt"; then
  echo "weights: MISSING segformer_best.pt" >&2
  missing=1
fi

if [ "$missing" -ne 0 ]; then
  echo "Put yolo_best.pt and segformer_best.pt on the runner, then set WEIGHTS_DIR or copy them into config/." >&2
  echo "Searched: ${candidates[*]}" >&2
  exit 1
fi
