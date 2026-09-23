# Segmentation service — SegFormer FP16 + HTTP API

Веса лежат в **`app/segmentation_service/weights/`** (`best_iou.pth`, `last_epoch.pth`). Обучение пишет сюда же через [`app/ml_core/config/agvision.yaml`](../ml_core/config/agvision.yaml).

## Структура

```
segmentation_service/
  weights/          # чекпоинты (.pth в .gitignore)
  config.yaml
  runtime.py        # загрузка модели
  inference.py      # FP16 forward
  pipeline.py         # RGB+NIR → полигон
  app.py            # FastAPI
  cli.py
```

## Запуск

```bash
pip install -e . -r app/ml_core/requirements.txt -r app/segmentation_service/requirements.txt

python -m segmentation_service --rgb photo.jpg --out result.json
uvicorn segmentation_service.app:app --host 0.0.0.0 --port 8080
```

Публичный web UI обслуживает `api_gateway` на порту 5173 и проксирует запросы в этот сервис. Контракт сегментации: `GET /api/v1/segmentation/health`, `POST /api/v1/segmentation/segment` (поле `file`). Старый API: `POST /v1/segment` (поле `rgb`).
