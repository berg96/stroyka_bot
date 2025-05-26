import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from loguru import logger

from config import config
from handlers import router as handlers_router
from utils.logger import setup_logging

setup_logging()


async def main():
    logger.info("Бот запускается...")
    bot = Bot(token=config.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(handlers_router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
