# Model serving — SegFormer FP16 + HTTP API

Веса лежат в **`core/model/weights/`** (`best_iou.pth`, `last_epoch.pth`). Обучение пишет сюда же (`core/config/agvision.yaml` → `output_dir: model/weights` относительно `core/`).

## Структура

```
model/
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
pip install -e . -r core/requirements.txt -r core/model/requirements.txt

python -m model --rgb photo.jpg --out result.json
uvicorn model.app:app --host 0.0.0.0 --port 8080
```

UI: [http://localhost:8080](http://localhost:8080) (статика из `web/`). Контракт фронта: `GET /api/v1/segmentation/health`, `POST /api/v1/segmentation/segment` (поле `file`). Старый API: `POST /v1/segment` (поле `rgb`).
