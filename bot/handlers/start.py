from aiogram import Router
from aiogram.types import Message
from aiogram.filters import CommandStart

from bot.keyboards.reply import main_menu
from bot.utils.logger import log_user_action

router = Router()

@log_user_action('/start')
@router.message(CommandStart())
async def start_handler(message: Message):
    await message.answer("Привет! Что будем делать?", reply_markup=main_menu)
