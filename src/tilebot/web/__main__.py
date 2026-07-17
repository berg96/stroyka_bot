"""Запуск мини-аппа: uvicorn на локальном порту, наружу его выставляет nginx.

    uv run python -m tilebot.web
"""

import asyncio
import logging
from pathlib import Path

import uvicorn

from tilebot.config import get_settings
from tilebot.storage import Storage
from tilebot.web.app import create_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def main() -> None:
    settings = get_settings()

    db_path = Path(settings.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    storage = Storage(str(db_path))
    # Бот и мини-апп смотрят в одну базу. Таблицы обычно уже созданы ботом, но
    # порядок запуска не гарантирован — init() идемпотентен.
    asyncio.run(storage.init())

    uvicorn.run(
        create_app(storage=storage, settings=settings),
        host=settings.web_host,
        port=settings.web_port,
        access_log=False,
    )


if __name__ == "__main__":
    main()
