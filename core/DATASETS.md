# Датасеты

## Agriculture-Vision (обучение)

- Репозиторий: https://github.com/SHI-Labs/Agriculture-Vision
- Hugging Face: https://huggingface.co/datasets/shi-labs/Agriculture-Vision
- Регистрация (официально): https://www.agriculture-vision.com

Тайлы **512×512**, каналы **RGB + NIR**. Для границ полей:

- `boundaries/` — маска границы поля
- `masks/` — валидная область аннотации (для метрик)

Скачивание:

```bash
python core/scripts/download_agvision.py --extract
```

Ожидаемая структура после распаковки:

```
data/agvision/Agriculture-Vision-2021/
  train/images/rgb/
  train/images/nir/
  train/boundaries/
  train/masks/
  val/...
  test/...
```

## Продакшен (ТЗ)

Снимки [dzz.by](https://dzz.by) GeoTIFF + SHP ~2000 полей — fine-tune SegFormer после Ag-Vision.
