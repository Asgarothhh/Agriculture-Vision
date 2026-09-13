# Agriculture Vision — QGIS plugin

Плагин ходит в HTTP API команды **core** (`POST /api/v1/segmentation/segment`).
Копии `field_detecter/` здесь нет.

## Запуск

1. Поднять API из корня репозитория:
   ```bash
   pip install -e . -r core/requirements.txt -r core/model/requirements.txt
   uvicorn model.app:app --host 0.0.0.0 --port 8080
   ```
2. В QGIS: **Модули → Управление → Установить из ZIP/папки** → каталог `plugin/`.
3. URL API по умолчанию: `http://127.0.0.1:8080`

## Вкладки

| Вкладка | Функция |
|---------|---------|
| Подключение | URL API, проверка health, mock-режим |
| Сегментация | растр → полигоны через core |
| Классификация | ждёт endpoint, которого в core пока нет |
| Журнал | лог операций |
