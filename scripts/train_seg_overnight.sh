set -euo pipefail
cd "$(dirname "$0")/.."
export PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"

if [[ -d .venv ]]; then
  source .venv/bin/activate
fi

echo "=== SegFormer overnight train ==="
echo "Config: app/ml_core/config/agvision.yaml"
echo "Logs: app/segmentation_service/weights/train.log"
mkdir -p app/segmentation_service/weights

python -m ml_core.train_seg --config app/ml_core/config/agvision.yaml 2>&1 | tee app/segmentation_service/weights/train.log

echo "Done. Best: app/segmentation_service/weights/best_iou.pth"
