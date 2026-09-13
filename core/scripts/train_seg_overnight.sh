set -euo pipefail
cd "$(dirname "$0")/.."
export PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"

if [[ -d .venv ]]; then
  source .venv/bin/activate
fi

echo "=== SegFormer overnight train ==="
echo "Config: config/agvision.yaml"
echo "Logs: model/weights/train.log"
mkdir -p model/weights

python -m field_detecter.train_seg --config config/agvision.yaml 2>&1 | tee model/weights/train.log

echo "Done. Best: model/weights/best_iou.pth"
