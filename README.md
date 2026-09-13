# Field Detecter — ViT границы полей + детекция точек

Сегментация границ сельхозучастков (**SegFormer / ViT**, 4 канала RGB+NIR) и детекция деревьев/столбов (**YOLO26**) на датасете [Agriculture-Vision](https://github.com/SHI-Labs/Agriculture-Vision).

Метрики по ТЗ §5.1: IoU ≥ 0.90, Recall ≥ 0.95, Precision ≥ 0.90 (поля); F1 ≥ 0.80 (точки, на pseudo-GT).

## Backend services

`app/` разделяет backend на независимые компоненты:

- `api_gateway/` — публичный Express-сервис, раздаёт `web/` и проксирует API.
- `users_service/` — Express-сервис учётных записей, JWT и профиля.
- `segmentation_service/` — FastAPI-сервис инференса SegFormer и локальной очереди задач.
- `ml_core/` — обучение, датасет, SegFormer/YOLO и геообработка, используемые сервисом сегментации.

## Результаты

- Первый прогон

```
Epoch: 2 val: {'iou_mean': 0.9398277102289697, 'precision_mean': 0.9424682089160502, 'recall_mean': 0.9955257925503495, 'n_samples': 1000}
```

- Второй прогон

```
Epoch: 12 val: {'iou_mean': 0.9461152559973611, 'precision_mean': 0.9513153409510501, 'recall_mean': 0.9928616511294276, 'n_samples': 1000}
```

- Контрольный прогон
  ```
  Итог val: {'iou_mean': 0.940880640879388, 'precision_mean': 0.9569229348797582, 'recall_mean': 0.9781622553366535, 'n_samples': 18334}
  ```

[скачать модельку](https://disk.yandex.by/d/K2Ll5HfISWNJ-w)

## Быстрый старт

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e . -r app/ml_core/requirements.txt -r app/segmentation_service/requirements.txt

# 1. Скачать Agriculture-Vision (~21 GB)
python scripts/download_agvision.py --extract

# 2. Обучение SegFormer
python -m ml_core.train_seg --config app/ml_core/config/agvision.yaml
# или на ночь:
bash scripts/train_seg_overnight.sh

# 3. Псевдоразметка + YOLO26
python -m ml_core.pseudo_points --config app/ml_core/config/agvision.yaml
python -m ml_core.train_det --config app/ml_core/config/agvision.yaml
```

Блокнот end-to-end: [`notebooks/train_field_vit.ipynb`](notebooks/train_field_vit.ipynb)

Тест инференса и полигоны: [`notebooks/test_segmentation_polygons.ipynb`](notebooks/test_segmentation_polygons.ipynb)

Конфиг: [`app/ml_core/config/agvision.yaml`](app/ml_core/config/agvision.yaml)

## Продакшен (FP16 + API)

Слой интеграции: [`app/segmentation_service/README.md`](app/segmentation_service/README.md) — веса в `app/segmentation_service/weights/best_iou.pth`, FP16, FastAPI и CLI.

```bash
# Terminal 1 — FastAPI ML service
uvicorn segmentation_service.app:app --host 0.0.0.0 --port 8080

# Terminal 2 — users service
cd app/users_service && npm install && npm start

# Terminal 3 — public gateway and web UI
cd app/api_gateway && npm install && npm start
```

Откройте [http://localhost:5173](http://localhost:5173). Gateway проксирует auth в `users_service` (`:5174`), а сегментацию в `segmentation_service` (`:8080`). Сегментация: `POST /api/v1/segmentation/segment`.

QGIS: каталог [`plugin/`](plugin/).

## Структура

```
app/
  api_gateway/          # Express: публичные API и web
  users_service/        # Express: JWT и учётные записи
  segmentation_service/ # FastAPI + FP16 + локальная JobQueue
  ml_core/              # датасет, SegFormer, YOLO, полигоны
web/                    # фронтенд
plugin/                 # QGIS HTTP-клиент, без torch
```
