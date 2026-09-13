# Field Detecter — ViT границы полей + детекция точек

Сегментация границ сельхозучастков (**SegFormer / ViT**, 4 канала RGB+NIR) и детекция деревьев/столбов (**YOLO26**) на датасете [Agriculture-Vision](https://github.com/SHI-Labs/Agriculture-Vision).

Метрики по ТЗ §5.1: IoU ≥ 0.90, Recall ≥ 0.95, Precision ≥ 0.90 (поля); F1 ≥ 0.80 (точки, на pseudo-GT).

## Ветки (три команды)

Один коммит-база, дальше каждая команда только в своей папке. В `main` — merge из трёх, не друг в друга.

| Ветка | Папка | Кто |
|-------|--------|-----|
| `core` | `core/` | обучение, FastAPI, Express (JWT/прокси) |
| `web` | `web/` | только UI (HTML/JS/CSS) |
| `plugin` | `plugin/` | QGIS, только HTTP к core |
| `docker` | всё дерево | интеграционный снимок (пока default на GitHub — старый `main`) |

Поток: `docker` (или `main`) → своя ветка каждый день; готовое — PR **в `docker`/`main`**.

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
pip install -e . -r core/requirements.txt -r core/model/requirements.txt

# 1. Скачать Agriculture-Vision (~21 GB)
python core/scripts/download_agvision.py --extract

# 2. Обучение SegFormer
python -m field_detecter.train_seg --config core/config/agvision.yaml
# или на ночь:
bash core/scripts/train_seg_overnight.sh

# 3. Псевдоразметка + YOLO26
python -m field_detecter.pseudo_points --config core/config/agvision.yaml
python -m field_detecter.train_det --config core/config/agvision.yaml
```

Блокнот end-to-end: [`core/notebooks/train_field_vit.ipynb`](core/notebooks/train_field_vit.ipynb)

Тест инференса и полигоны: [`core/notebooks/test_segmentation_polygons.ipynb`](core/notebooks/test_segmentation_polygons.ipynb)

Конфиг: [`core/config/agvision.yaml`](core/config/agvision.yaml)

## Продакшен (FP16 + API)

Слой интеграции: [`core/model/README.md`](core/model/README.md) — веса в `core/model/weights/best_iou.pth`, FP16, FastAPI, CLI `python -m model`.

```bash
uvicorn model.app:app --host 0.0.0.0 --port 8080
```

Откройте [http://localhost:8080](http://localhost:8080). Сегментация: `POST /api/v1/segmentation/segment`. Нужен чекпоинт `core/model/weights/best_iou.pth`.

Опционально Node с JWT (проксирует ML на `:8080`):

```bash
cd core && npm install && npm start
```

QGIS: каталог [`plugin/`](plugin/).

## Структура

```
core/                   # ветка core: весь бэк
  field_detecter/       # датасет, SegFormer, YOLO, полигоны
  model/                # FastAPI + FP16
  server.js             # Express: JWT, Postgres, прокси на FastAPI
  config/agvision.yaml
  scripts/
web/                    # ветка web: только фронт
plugin/                 # ветка plugin (HTTP-клиент, без torch)
```
