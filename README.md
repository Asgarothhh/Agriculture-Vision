# АгроВижион — backend

Асинхронный REST API (`/api/v1`) для распознавания сельхозугодий. Модели сегментации загружаются **из файлов весов** в процессе API/Celery, отдельного ML-сервера нет.

Спецификация: [`spec/spec_backend.md`](spec/spec_backend.md).  
Локальный инференс и раскладка репозитория: [`spec/spec_backend_local_ml.md`](spec/spec_backend_local_ml.md).

## Быстрый старт

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .

cp .env.example .env
# DATABASE_URL: postgresql+asyncpg://developer:<pass>@localhost:5432/agriculture-vision

alembic upgrade head
python -m app.core.seed

uvicorn app.main:app --reload --port 8000
# другой терминал:
celery -A app.tasks_service.workers worker -Q ml-gpu,cpu -l info
```

Swagger: [http://localhost:8000/api/v1/docs](http://localhost:8000/api/v1/docs).  
Авторизация: `Authorization: Bearer <access_token>`.

`python -m app.core.seed` создаёт справочники и демо-пользователей (пароль у всех `ValidPass1!`):

| Email | Роль |
|---|---|
| `admin@agrovision.dev` | Администратор |
| `agronom@agrovision.dev` | Агроном |
| `operator@agrovision.dev` | Оператор |

В DBeaver подключайтесь к **тому же порту, что в `.env`** (локальный PostGIS-контейнер — **5433**, не системный `:5432` без PostGIS). После seed у агронома видны папка «Сезон 2026», слой «Демо поле», задачи PENDING/FAILED/COMPLETED.

Веса: `config/yolo_best.pt`, `config/segformer_best.pt` (или пути `YOLO_WEIGHTS_PATH` / `SEGFORMER_WEIGHTS_PATH`).

```bash
pytest -q
```

Docker Compose: `docker compose -f deploy/docker-compose.yml up -d --build`.

Не-backend артефакты (QGIS, ноутбуки, Express) — в [`extras/`](extras/).
