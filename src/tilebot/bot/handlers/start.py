"""Приветствие и справка."""

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from tilebot.bot import keyboards as kb
from tilebot.storage import Storage

router = Router(name="start")

HELLO = """<b>Помощник плиточника</b> 🧱

Считаю то, что обычно считают на калькуляторе и записывают на бумажку.

<b>🧱 Плитка</b> — раскладка по стене или полу: сколько плитки, где встанет
подрезка и не выйдет ли по краю тонкая полоска. Плюс клей, затирка, СВП, грунт,
гидроизоляция — списком «что купить».

<b>📐 Площадь</b> — площадь комнаты по замерам рулеткой: прямоугольник,
треугольник, четырёхугольник по сторонам и диагонали, Г-образная комната с
коробом.

<b>📋 Мои объекты</b> — стены копятся в объекте, закупка сводится в один список.

<b>💰 Прайс</b> — твои цены за работу. По ним соберу смету заказчику в PDF со
схемами раскладки.

Размеры пиши как удобно: <code>2.7 2.5</code> или <code>2700 2500</code> — разберусь."""


@router.message(CommandStart())
async def start(message: Message, state: FSMContext, storage: Storage) -> None:
    await state.clear()
    await storage.get_or_create_user(message.from_user.id)
    await message.answer(HELLO, reply_markup=kb.MAIN_MENU)


@router.message(Command("help"))
async def help_cmd(message: Message) -> None:
    await message.answer(HELLO, reply_markup=kb.MAIN_MENU)


@router.message(Command("cancel", "отмена"))
async def cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменил. Что считаем?", reply_markup=kb.MAIN_MENU)
