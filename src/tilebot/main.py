"""Точка входа: поллинг, DI хранилища, аккуратные ошибки."""

import asyncio
import logging
from contextlib import suppress
from pathlib import Path
from typing import Any

from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import CallbackQuery, ErrorEvent, Message, TelegramObject

from tilebot.bot.handlers import area, money, photos, price, projects, start, tiling
from tilebot.config import get_settings
from tilebot.storage import Storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


class StorageMiddleware(BaseMiddleware):
    """Прокидывает хранилище в хендлеры — они принимают его аргументом storage."""

    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    async def __call__(self, handler, event: TelegramObject, data: dict[str, Any]):
        data["storage"] = self.storage
        return await handler(event, data)


async def on_error(event: ErrorEvent) -> bool:
    """Мастер не должен видеть трейсбек — он должен видеть, что делать дальше."""
    logger.exception("Ошибка при обработке апдейта", exc_info=event.exception)

    call = event.update.callback_query
    target = event.update.message or (call.message if call else None)

    if isinstance(call, CallbackQuery):
        with suppress(Exception):  # колбэк мог быть уже отвечен — не страшно
            await call.answer()

    if isinstance(target, Message):
        await target.answer(
            "Что-то пошло не так на моей стороне. Попробуй ещё раз, "
            "а если повторится — напиши Тёме.\n\n/cancel — начать заново."
        )
    return True


async def main() -> None:
    settings = get_settings()

    db_path = Path(settings.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    storage = Storage(str(db_path))
    await storage.init()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.update.middleware(StorageMiddleware(storage))
    dp.errors.register(on_error)
    dp.include_routers(
        start.router,
        area.router,
        projects.router,
        money.router,
        photos.router,
        price.router,
        tiling.router,
    )

    me = await bot.get_me()
    logger.info("Бот @%s запущен", me.username)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
