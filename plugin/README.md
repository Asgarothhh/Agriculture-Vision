# Agriculture Vision — QGIS plugin

Плагин ходит в HTTP API `segmentation_service` (`POST /api/v1/segmentation/segment`).
Копии `ml_core/` здесь нет.

## Запуск

1. Поднять API из корня репозитория:
   ```bash
   pip install -e . -r app/ml_core/requirements.txt -r app/segmentation_service/requirements.txt
   uvicorn segmentation_service.app:app --host 0.0.0.0 --port 8080
   ```
2. В QGIS: **Модули → Управление → Установить из ZIP/папки** → каталог `plugin/`.
3. URL API по умолчанию: `http://127.0.0.1:8080`

## Вкладки

| Вкладка | Функция |
|---------|---------|
| Подключение | URL API, проверка health, mock-режим |
| Сегментация | растр → полигоны через segmentation service |
| Классификация | ждёт endpoint, которого в сервисе пока нет |
| Журнал | лог операций |
