#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${WEIGHTS_DEST:-$ROOT/config}"
mkdir -p "$DEST"

candidates=()
if [ -n "${WEIGHTS_DIR:-}" ]; then
  candidates+=("$WEIGHTS_DIR")
fi
candidates+=("$DEST")
if [ "${WEIGHTS_ONLY:-}" != "1" ]; then
  candidates+=(
    "/var/agriculture-vision/config"
    "/var/agriculture-vision"
    "/opt/agriculture-vision/config"
    "/opt/agriculture-vision"
    "${HOME:-/root}/agriculture-vision/config"
    "${HOME:-/root}/config"
    "${HOME:-/root}/weights"
  )
fi

file_ok() {
  [ -f "$1" ] && [ -s "$1" ]
}

copy_from_path() {
  local src="$1" dest_name="$2"
  if ! file_ok "$src"; then
    return 1
  fi
  if [ "$src" != "$DEST/$dest_name" ]; then
    cp -a "$src" "$DEST/$dest_name"
    echo "weights: copied $src -> $DEST/$dest_name ($(du -h "$DEST/$dest_name" | cut -f1))"
  else
    echo "weights: using $DEST/$dest_name ($(du -h "$DEST/$dest_name" | cut -f1))"
  fi
}

copy_named() {
  local dest_name="$1"
  shift
  if file_ok "$DEST/$dest_name"; then
    echo "weights: using $DEST/$dest_name ($(du -h "$DEST/$dest_name" | cut -f1))"
    return 0
  fi
  local name dir
  for name in "$dest_name" "$@"; do
    for dir in "${candidates[@]}"; do
      if copy_from_path "$dir/$name" "$dest_name"; then
        return 0
      fi
    done
  done
  return 1
}

copy_glob() {
  local dest_name="$1"
  local pattern="$2"
  if file_ok "$DEST/$dest_name"; then
    return 0
  fi
  local dir src
  shopt -s nullglob
  for dir in "${candidates[@]}"; do
    for src in "$dir"/$pattern; do
      case "$(basename "$src")" in
        segformer_best.pt) continue ;;
      esac
      if copy_from_path "$src" "$dest_name"; then
        shopt -u nullglob
        return 0
      fi
    done
  done
  shopt -u nullglob
  return 1
}

extract_from_docker() {
  local dest_name="$1"
  if file_ok "$DEST/$dest_name"; then
    return 0
  fi
  if [ "${WEIGHTS_ONLY:-}" = "1" ] || [ "${WEIGHTS_SKIP_IMAGE_FALLBACKS:-}" = "1" ]; then
    return 1
  fi
  if ! command -v docker >/dev/null 2>&1; then
    return 1
  fi
  local img id
  while IFS= read -r img; do
    [ -n "$img" ] || continue
    case "$img" in
      *"<none>"*) continue ;;
    esac
    id="$(docker create "$img" 2>/dev/null)" || continue
    if docker cp "$id:/app/config/$dest_name" "$DEST/$dest_name" >/dev/null 2>&1 \
      && file_ok "$DEST/$dest_name"; then
      docker rm "$id" >/dev/null 2>&1 || true
      echo "weights: extracted $dest_name from image $img ($(du -h "$DEST/$dest_name" | cut -f1))"
      return 0
    fi
    docker rm "$id" >/dev/null 2>&1 || true
    rm -f "$DEST/$dest_name"
  done < <(docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | grep -E 'agriculture-vision-(api|worker)' || true)
  return 1
}

extract_from_k8s() {
  local dest_name="$1"
  if file_ok "$DEST/$dest_name"; then
    return 0
  fi
  if [ "${WEIGHTS_ONLY:-}" = "1" ] || [ "${WEIGHTS_SKIP_IMAGE_FALLBACKS:-}" = "1" ]; then
    return 1
  fi
  if ! command -v kubectl >/dev/null 2>&1; then
    return 1
  fi
  local ns="${KUBE_NAMESPACE:-ml-service}"
  local label pod
  for label in "app=agri-api" "app=agri-worker"; do
    pod="$(kubectl get pods -n "$ns" -l "$label" --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
    [ -n "$pod" ] || continue
    if kubectl cp "$ns/$pod:/app/config/$dest_name" "$DEST/$dest_name" >/dev/null 2>&1 \
      && file_ok "$DEST/$dest_name"; then
      echo "weights: copied $dest_name from pod $pod ($(du -h "$DEST/$dest_name" | cut -f1))"
      return 0
    fi
    rm -f "$DEST/$dest_name"
  done
  return 1
}

ensure() {
  local dest_name="$1"
  shift
  copy_named "$dest_name" "$@" || true
  if [ "$dest_name" = "yolo_best.pt" ]; then
    copy_glob "$dest_name" "yolo*.pt" || true
  fi
  extract_from_docker "$dest_name" || true
  extract_from_k8s "$dest_name" || true
  file_ok "$DEST/$dest_name"
}

dump_search() {
  echo "Put yolo_best.pt and segformer_best.pt on the runner, then set WEIGHTS_DIR or copy them into config/." >&2
  echo "Searched: ${candidates[*]}" >&2
  local dir
  for dir in "${candidates[@]}"; do
    if [ -d "$dir" ]; then
      echo "weights: listing $dir" >&2
      ls -lh "$dir" >&2 || true
    fi
  done
}

missing=0
if ! ensure "yolo_best.pt" "yolo.pt" "yolo_seg.pt" "yolo_seg_26.pt"; then
  echo "weights: MISSING yolo_best.pt" >&2
  missing=1
fi
if ! ensure "segformer_best.pt"; then
  echo "weights: MISSING segformer_best.pt" >&2
  missing=1
fi

if [ "$missing" -ne 0 ]; then
  dump_search
  exit 1
fi
