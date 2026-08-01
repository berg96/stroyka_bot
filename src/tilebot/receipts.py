"""Файлы чеков: лежат на диске рядом с базой.

Фото объекта мы храним как `file_id` — файл живёт у Telegram, качать его незачем.
С чеком так нельзя: его показывает и мини-апп, а `file_id` вне бота бесполезен.
Поэтому одна дорога для обоих каналов — байты на диске: бот скачивает присланное
фото, мини-апп кладёт загруженный файл, читают оба через один эндпоинт.

Каталог берётся из `RECEIPTS_DIR` (по умолчанию рядом с базой, `data/receipts`) —
в контейнере это bind-mount, то есть чеки переживают пересборку образа.
"""

import os
import re
from pathlib import Path

DIR = Path(os.getenv("RECEIPTS_DIR", "data/receipts"))

# Чем открывается фото чека. Всё прочее (pdf, heic) не принимаем: показать в
# мини-аппе не сможем, а молча положить файл, который потом не откроется, — хуже
# чем отказать сразу.
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp"}
MAX_BYTES = 10 * 1024 * 1024


def ext_of(filename: str) -> str:
    """Расширение из имени файла, приведённое к нижнему регистру. '' — не наше."""
    ext = Path(filename or "").suffix.lower()
    return ext if ext in ALLOWED_EXT else ""


def ext_of_type(content_type: str | None) -> str:
    """Расширение по MIME — фолбэк, когда пикер прислал файл без имени."""
    return {
        "image/jpeg": ".jpg", "image/jpg": ".jpg",
        "image/png": ".png", "image/webp": ".webp",
    }.get((content_type or "").lower(), "")


def save(expense_id: int, data: bytes, ext: str = ".jpg") -> str:
    """Записать чек и вернуть имя файла для БД."""
    DIR.mkdir(parents=True, exist_ok=True)
    name = f"{expense_id}{ext}"
    (DIR / name).write_bytes(data)
    return name


def path(name: str) -> Path | None:
    """Путь к чеку. None — имени нет или оно не наше (защита от `../`)."""
    if not name or not re.fullmatch(r"\d+\.[a-z]{3,4}", name):
        return None
    file = DIR / name
    return file if file.is_file() else None


def remove(name: str) -> None:
    file = path(name)
    if file:
        file.unlink(missing_ok=True)
