# АгроВижион

Веб-приложение и REST API (`/api/v1`) для распознавания сельхозугодий. Модели сегментации загружаются **из файлов весов** в процессе API/Celery, отдельного ML-сервера нет.

Спецификация: [`spec/spec_backend.md`](spec/spec_backend.md).  
Локальный инференс: [`spec/spec_backend_local_ml.md`](spec/spec_backend_local_ml.md).

## Быстрый старт (локально)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .

cp .env.example .env
# DATABASE_URL: postgresql+asyncpg://developer:<pass>@localhost:5432/agriculture-vision

alembic upgrade head
python -m app.core.seed
```

Веса: `config/yolo_best.pt`, `config/segformer_best.pt` (или `YOLO_WEIGHTS_PATH` / `SEGFORMER_WEIGHTS_PATH`).
Если SegFormer распакован в `config/segformer_best/best_iou/`:

```bash
python scripts/pack_segformer_weights.py
```

Три терминала:

```bash
uvicorn app.main:app --reload --port 8000
celery -A app.tasks_service.workers worker -Q ml-gpu,cpu -l info
cd frontend && npm install && npm run dev
```

UI: [http://localhost:5173](http://localhost:5173) (Vite проксирует `/api` на `:8000`).  
Swagger: [http://localhost:8000/api/v1/docs](http://localhost:8000/api/v1/docs).  
Авторизация: `Authorization: Bearer <access_token>`.

`python -m app.core.seed` создаёт справочники и демо-пользователей (пароль у всех `ValidPass1!`):

| Email | Роль |
|---|---|
| `admin@agrovision.dev` | Администратор |
| `agronom@agrovision.dev` | Агроном |
| `operator@agrovision.dev` | Оператор |

В DBeaver подключайтесь к **тому же порту, что в `.env`** (локальный PostGIS-контейнер — **5433**, не системный `:5432` без PostGIS).

```bash
pytest -q
cd frontend && npm test
```

Playwright (нужны API на `:8000` и `npm run dev`):

```bash
cd frontend && npx playwright install chromium && npm run test:e2e
```

Маркер `@pytest.mark.ml` — живая загрузка весов; в CI без GPU/файлов тесты весов пропускаются.

## Подключение dzz.by

Ортофотоподложка идёт через FastAPI `POST /api/v1/dzz/connect` (нужна сессия пользователя), тайлы — `GET /api/v1/dzz/tiles/{z}/{x}/{y}`.

1. Войдите в приложение (например `agronom@agrovision.dev` / `ValidPass1!`).
2. Нажмите **«Подключить dzz.by»** в шапке (или пилюлю `dzz.by · Не подключено`). Откроется панель настроек, подложка переключится на ортофото.
3. Если портал требует учётку — в блоке **«Доступ к dzz.by»** укажите логин и пароль. Если ImageServer открытый, поля можно оставить пустыми.
4. Адрес по умолчанию:  
   `https://www.dzz.by/arcgis/rest/services/georesursDDZ/Belarus_web_mercator_all/ImageServer`
   (ортофото Беларуси в Web Mercator, не слой `Polya_all` — он даёт пустую карту в городе).  
   (корень ImageServer, без `/tile/{z}/{y}/{x}`). При необходимости замените на URL из [geodzz.by](https://geodzz.by/izuchdz).
5. Нажмите **«Проверить подключение»**. Успех: пилюля `dzz.by · Онлайн`, тост «dzz.by подключён», внизу карты — участки областей.
6. В списке «Подложка» оставьте «Ортофото dzz.by».

Отключение: **«Выйти из dzz.by»** в тех же настройках.

Ошибки: `Неверные учётные данные dzz.by` — проверьте логин/пароль; `dzz.by недоступен` — сеть или URL; пилюля `dzz.by · Ошибка` — сервис ответил, но не `online`.

## Docker Compose

Один вход: [http://localhost](http://localhost) (Nginx отдаёт `frontend/dist` и проксирует `/api/`).

```bash
docker compose -f deploy/docker-compose.yml up -d --build
```
