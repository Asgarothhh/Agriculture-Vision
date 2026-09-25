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

Пароль dzz.by не хранится в браузере. `POST /api/v1/dzz/connect` проверяет логин/пароль у ArcGIS ImageServer, сохраняет их на сервере в зашифрованной cookie-сессии `dzz_sid` (не в учётке приложения) и дальше сам подставляет HTTP Basic Auth. Тайлы и query идут через прокси `GET /api/v1/dzz/arcgis/...`.

1. Войдите в приложение (например `agronom@agrovision.dev` / `ValidPass1!`).
2. Нажмите **«Подключить dzz.by»** в шапке (или пилюлю `dzz.by · Не подключено`). Откроется панель настроек.
3. В блоке **«Доступ к dzz.by»** укажите логин и пароль портала. Адрес по умолчанию:  
   `https://www.dzz.by/arcgis/rest/services/georesursDDZ/Polya_all/ImageServer`  
   (корень ImageServer; суффикс `WMTSCapabilities.xml` отбрасывается автоматически).
4. Нажмите **«Проверить подключение»**. Успех: поле пароля очищается, пилюля `dzz.by · Онлайн`, подложка переключается на ортофото, внизу карты — участки покрытия.
5. Зум 10–14 запрашивает REST `tile/{z-8}/{y}/{x}`; вне этого диапазона — `exportImage` с bbox Web Mercator.

Отключение: **«Выйти из dzz.by»**. Сессия живёт 8 часов и переживает перезапуск API (файл `data/dzz-sessions.enc`).

Ошибки: `Неверные учётные данные dzz.by` — JSON 401/403 от ArcGIS; `dzz.by недоступен` — HTML-заглушка, сеть или 5xx. Матрица WMTS `GoogleMapsCompatible` у dzz.by часто отвечает 520 — клиент предлагает запасной набор.

## Docker Compose

Один вход: [http://localhost](http://localhost) (Nginx отдаёт `frontend/dist` и проксирует `/api/`).

```bash
docker compose -f deploy/docker-compose.yml up -d --build
```
