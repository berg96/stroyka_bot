"""Прайс мастера и его подпись в смете."""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from tilebot.bot import keyboards as kb
from tilebot.bot.parse import ParseError, single_number
from tilebot.core.estimate import money
from tilebot.storage import Storage

router = Router(name="price")

LABELS = {
    "wall_tiling": "Укладка плитки на стену, ₽/м²",
    "floor_tiling": "Укладка плитки на пол, ₽/м²",
    "waterproofing": "Гидроизоляция, ₽/м²",
    "priming": "Грунтовка, ₽/м²",
    "grouting": "Затирка швов, ₽/м²",
    "demolition": "Демонтаж старой плитки, ₽/м²",
    "min_order": "Минимальный заказ, ₽",
}


class Price(StatesGroup):
    value = State()
    signature = State()


@router.message(F.text == "💰 Прайс")
async def show_price(message: Message, storage: Storage) -> None:
    user = await storage.get_or_create_user(message.from_user.id)
    price = user.price

    lines = ["<b>Твой прайс</b>", "<i>По нему считается смета заказчику.</i>", ""]
    for field, label in LABELS.items():
        lines.append(f"• {label}: <b>{money(getattr(price, field))}</b>")

    signature = " · ".join(x for x in (user.name, user.phone) if x)
    lines += ["", f"Подпись в смете: {signature or '<i>не задана</i>'} — /подпись"]
    lines += ["", "Нажми, что поменять:"]

    await message.answer("\n".join(lines), reply_markup=kb.price_fields())


@router.callback_query(F.data.startswith("price:"))
async def ask_value(call: CallbackQuery, state: FSMContext) -> None:
    field = call.data.split(":", 1)[1]
    await state.update_data(field=field)
    await state.set_state(Price.value)
    await call.answer()
    await call.message.answer(f"<b>{LABELS[field]}</b>\n\nНовое значение числом:")


@router.message(Price.value)
async def set_value(message: Message, state: FSMContext, storage: Storage) -> None:
    try:
        value = single_number(message.text or "", minimum=0, maximum=1_000_000)
    except ParseError as e:
        await message.answer(f"{e}\n\nНапиши число, например <code>1200</code>")
        return

    data = await state.get_data()
    field = data["field"]

    user = await storage.get_or_create_user(message.from_user.id)
    price = user.price
    setattr(price, field, value)
    user.price = price
    await storage.save_user(user)

    await state.clear()
    await message.answer(
        f"{LABELS[field]} — теперь <b>{money(value)}</b>.", reply_markup=kb.MAIN_MENU
    )
    await show_price(message, storage)


@router.message(Command("подпись", "signature"))
async def ask_signature(message: Message, state: FSMContext) -> None:
    await state.set_state(Price.signature)
    await message.answer(
        "Имя и телефон для сметы — одной строкой:\n\n"
        "<code>Александр Приймак, +7 911 491-17-54</code>"
    )


@router.message(Price.signature)
async def set_signature(message: Message, state: FSMContext, storage: Storage) -> None:
    raw = (message.text or "").strip()
    name, _, phone = raw.partition(",")

    user = await storage.get_or_create_user(message.from_user.id)
    user.name = name.strip()[:128]
    user.phone = phone.strip()[:32]
    await storage.save_user(user)

    await state.clear()
    await message.answer(
        f"Готово. В смете будет: <b>{user.name}</b>"
        + (f" · {user.phone}" if user.phone else ""),
        reply_markup=kb.MAIN_MENU,
    )
