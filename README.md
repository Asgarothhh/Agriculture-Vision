# Agriculture Vision — Docker-пакет для заказчика

4 контейнера:

| Сервис | Контейнер | Порт | Назначение |
|--------|-----------|------|------------|
| **frontend** | `av-frontend` | **5173** | Веб-интерфейс + авторизация |
| **backend** | `av-backend` | **8000** | ML API (сегментация / классификация) |
| **db** | `av-db` | **5432** | PostgreSQL (пользователи) |
| **models** | `av-models` | — | Веса YOLO + SegFormer → volume `/models` |

QGIS-плагин в этот архив **не входит** (отдаётся отдельно).

## Требования

- Docker Engine 24+
- Docker Compose v2 (`docker compose`)
- ~10 GB свободного места (образы + веса ~0.8 GB)
- CPU достаточно для демо (GPU не обязателен)

## Быстрый старт

```bash
# 1) Распаковать архив
tar -xzf agriculture-vision-docker.tar.gz
cd agriculture-vision-docker

# 2) Настройки (пароли)
cp .env.example .env
# при необходимости отредактируйте POSTGRES_PASSWORD и JWT_SECRET

# 3) Сборка и запуск
docker compose up -d --build

# 4) Открыть UI
# http://localhost:5173
```

Проверка:

```bash
docker compose ps
curl http://localhost:8000/api/v1/segmentation/health
curl http://localhost:5173/api/health
```

Логи:

```bash
docker compose logs -f backend
docker compose logs -f frontend
```

Остановка:

```bash
docker compose down
# с удалением данных БД и volume моделей:
# docker compose down -v
```

## Порты (можно менять в `.env`)

- `FRONTEND_PORT=5173` — сайт
- `BACKEND_PORT=8000` — ML API (также для QGIS: `http://<IP>:8000`)
- `DB_PORT=5432` — Postgres (обычно только localhost)

## Структура

```
agriculture-vision-docker/
├── docker-compose.yml
├── .env.example
├── README.md
├── backend/          # FastAPI + field_detecter
├── frontend/         # Express UI
├── models/           # Dockerfile + weights/*.pth|*.pt
└── db/init.sql       # схема users
```

## Веса моделей

Лежат в `models/weights/`:

- `best_iou.pth` — SegFormer
- `yolo_best.pt` — YOLO

Контейнер `models` при старте копирует их в Docker volume `model-data` (`/models` у backend).

## Сеть для демо в LAN

1. На сервере: `docker compose up -d --build`
2. Узнать IP: `hostname -I` / `ipconfig`
3. Открыть в браузере: `http://<IP>:5173`
4. QGIS на другом ПК: URL API = `http://<IP>:8000`

Firewall: TCP **5173** и **8000**.

## Примечания

- Первый `docker compose build` долгий (PyTorch CPU + зависимости).
- Классификация культур — stub (живой endpoint).
- Пароли по умолчанию в `.env.example` — смените перед продакшеном.
