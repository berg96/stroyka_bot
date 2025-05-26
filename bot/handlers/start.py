from aiogram import Router
from aiogram.types import Message
from aiogram.filters import CommandStart

from keyboards.reply import main_menu
from utils.logger import log_user_action

router = Router()


@router.message(CommandStart())
@log_user_action('/start')
async def start_handler(message: Message):
    await message.answer("Привет! Что будем делать?", reply_markup=main_menu)
