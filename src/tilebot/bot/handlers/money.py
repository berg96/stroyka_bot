"""Деньги по объекту: сумма договора, авансы, остаток.

С форумов мастеров: заказчик пропадает или «забывает» доплатить, поэтому аванс
берут вперёд. Держать это в голове по нескольким объектам нельзя — здесь оно
записано.
"""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from tilebot.bot import keyboards as kb
from tilebot.bot.parse import ParseError, amount_and_comment, single_number
from tilebot.core.estimate import money
from tilebot.storage import Project, Storage

router = Router(name="money")


class Money(StatesGroup):
    deal = State()
    payment = State()


def _card(project: Project) -> str:
    lines = [f"<b>{project.title}</b> — деньги", ""]

    if project.deal_amount:
        lines.append(f"Договорились: <b>{money(project.deal_amount)}</b>")
    else:
        lines.append("Сумма с заказчиком не записана.")

    if project.payments:
        lines.append("")
        for p in sorted(project.payments, key=lambda x: x.created_at):
            when = p.created_at.strftime("%d.%m")
            note = f" — {p.comment}" if p.comment else ""
            lines.append(f"• {when}: {money(p.amount)}{note}")
        lines.append(f"\nПолучено: <b>{money(project.paid)}</b>")
    else:
        lines.append("\nПлатежей пока нет.")

    if project.deal_amount:
        if project.due > 0:
            lines.append(f"Остаток с заказчика: <b>{money(project.due)}</b>")
        elif project.paid > project.deal_amount:
            lines.append(f"Переплата: <b>{money(project.paid - project.deal_amount)}</b>")
        else:
            lines.append("✅ Рассчитались полностью.")

    return "\n".join(lines)


@router.callback_query(F.data.startswith("money:"))
async def show_money(call: CallbackQuery, storage: Storage) -> None:
    project_id = int(call.data.split(":")[1])
    project = await storage.get_project(project_id, call.from_user.id)
    await call.answer()
    if not project:
        await call.message.answer("Объект не найден.")
        return

    await call.message.answer(_card(project), reply_markup=kb.money_actions(project_id))


@router.callback_query(F.data.startswith("setdeal:"))
async def ask_deal(call: CallbackQuery, state: FSMContext, storage: Storage) -> None:
    project_id = int(call.data.split(":")[1])
    await state.update_data(project_id=project_id)
    await state.set_state(Money.deal)
    await call.answer()

    project = await storage.get_project(project_id, call.from_user.id)
    hint = ""
    if project and project.surfaces:
        hint = "\n\n<i>Если уже собрал смету — можно взять её итог.</i>"

    await call.message.answer(f"На какую сумму договорились с заказчиком?{hint}")


@router.message(Money.deal)
async def set_deal(message: Message, state: FSMContext, storage: Storage) -> None:
    try:
        amount = single_number(message.text or "", minimum=0, maximum=100_000_000)
    except ParseError as e:
        await message.answer(f"{e}\n\nНапиши сумму числом, например <code>60000</code>")
        return

    data = await state.get_data()
    await state.clear()
    if not await storage.set_deal_amount(data["project_id"], message.from_user.id, amount):
        await message.answer("Объект не найден.", reply_markup=kb.MAIN_MENU)
        return

    project = await storage.get_project(data["project_id"], message.from_user.id)
    await message.answer(_card(project), reply_markup=kb.money_actions(project.id))


@router.callback_query(F.data.startswith("addpay:"))
async def ask_payment(call: CallbackQuery, state: FSMContext) -> None:
    project_id = int(call.data.split(":")[1])
    await state.update_data(project_id=project_id)
    await state.set_state(Money.payment)
    await call.answer()
    await call.message.answer(
        "Сколько получил и за что?\n\n"
        "<code>30000 аванс</code>\n"
        "<code>25000 расчёт</code>\n\n"
        "<i>Можно просто сумму.</i>"
    )


@router.message(Money.payment)
async def add_payment(message: Message, state: FSMContext, storage: Storage) -> None:
    try:
        amount, comment = amount_and_comment(message.text or "")
    except ParseError as e:
        await message.answer(f"{e}\n\nПример: <code>30000 аванс</code>")
        return

    data = await state.get_data()
    await state.clear()
    if not await storage.add_payment(data["project_id"], message.from_user.id, amount, comment):
        await message.answer("Объект не найден.", reply_markup=kb.MAIN_MENU)
        return

    project = await storage.get_project(data["project_id"], message.from_user.id)
    head = f"Записал: <b>{money(amount)}</b>" + (f" — {comment}" if comment else "")
    await message.answer(
        f"{head}\n\n{_card(project)}", reply_markup=kb.money_actions(project.id)
    )


@router.message(F.text == "💵 Долги")
async def debts(message: Message, storage: Storage) -> None:
    """Кто сколько должен — одним списком по всем объектам."""
    projects = await storage.list_projects(message.from_user.id, limit=50)
    owing = [p for p in projects if p.due > 0]

    if not owing:
        await message.answer(
            "Долгов нет — либо все рассчитались, либо суммы не записаны.",
            reply_markup=kb.MAIN_MENU,
        )
        return

    lines = ["<b>Должны тебе</b>", ""]
    for p in owing:
        lines.append(f"• {p.title}: <b>{money(p.due)}</b> <i>(из {money(p.deal_amount)})</i>")
    lines.append(f"\nВсего: <b>{money(sum(p.due for p in owing))}</b>")

    await message.answer("\n".join(lines), reply_markup=kb.projects_list(owing))
