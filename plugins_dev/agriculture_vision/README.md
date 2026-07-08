# Agriculture Vision — QGIS plugin

Плагин для QGIS 4, интегрирующий модули из папки `web/` (FastAPI backend).

## Запуск

1. **QGIS:** двойной клик `run_qgis_with_plugins.bat`
2. **Backend (опционально):** из папки `web/`:
   ```bash
   pip install -r docker/requirements.txt
   uvicorn app:app --host 0.0.0.0 --port 8000
   ```
3. В QGIS: **Модули → Agriculture Vision → Agriculture Vision…**

## Вкладки

| Вкладка | Функция |
|---------|---------|
| Подключение | URL API, проверка health, mock-режим |
| Сегментация | YOLO / SegFormer на растровом слое |
| Классификация | Определение культуры по полигону |
| Журнал | Лог операций |

## Mock-режим

Если backend не запущен, включите «Использовать заглушки» — UI работает с тестовыми данными (как в `web/backend/routers/classification_router.py`).

## Структура

```
agriculture_vision/
├── agriculture_vision_plugin.py   # точка входа
├── agriculture_vision_dialog.py     # интерфейс
├── api_client.py                    # HTTP → FastAPI
├── mock_client.py                   # заглушки
├── layer_utils.py                   # растр ↔ карта QGIS
└── constants.py                     # классы, пороги
```

## ТЗ

Файл `web/4.docx` в репозитории не найден. Реализация следует `web/docs/API_DOCUMENTATION.md` и роутерам в `web/backend/`.
