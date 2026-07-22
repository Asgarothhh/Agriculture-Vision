"""Сохранение файла из ipywidgets.FileUpload (v7 и v8)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator


def iter_file_upload(upload_value: Any) -> Iterator[tuple[str, bytes]]:
    """
    Разбор upload_widget.value:
    - v7: dict[name -> {content, metadata, ...}]
    - v8: tuple[dict] или tuple объектов с .name / .content
    """
    if not upload_value:
        return

    if isinstance(upload_value, dict):
        items = upload_value.items()
    elif isinstance(upload_value, (list, tuple)):
        items = []
        for item in upload_value:
            if isinstance(item, dict):
                items.append((item.get("name", "upload.png"), item))
            else:
                name = getattr(item, "name", None) or "upload.png"
                content = getattr(item, "content", None)
                if content is None and hasattr(item, "tobytes"):
                    content = item.tobytes()
                items.append((name, {"content": content}))
    else:
        return

    for name, info in items:
        if isinstance(info, dict):
            raw = info.get("content", b"")
        else:
            raw = info
        if isinstance(raw, memoryview):
            raw = raw.tobytes()
        if not isinstance(raw, (bytes, bytearray)):
            continue
        yield str(name), bytes(raw)


def save_first_upload(upload_value: Any, dest: Path) -> Path | None:
    """Пишет первый загруженный файл в dest (фиксированное имя для следующих ячеек)."""
    dest = Path(dest)
    for _name, content in iter_file_upload(upload_value):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        return dest
    return None
