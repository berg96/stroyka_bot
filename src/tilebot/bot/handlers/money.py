"""Деньги по объекту: сумма договора, авансы, остаток.

С форумов мастеров: заказчик пропадает или «забывает» доплатить, поэтому аванс
берут вперёд. Держать это в голове по нескольким объектам нельзя — здесь оно
записано.
"""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from tilebot import receipts
from tilebot.bot import keyboards as kb
from tilebot.core.estimate import money
from tilebot.core.parse import ParseError, amount_and_comment, single_number
from tilebot.storage import Project, Storage

router = Router(name="money")


class Money(StatesGroup):
    deal = State()
    payment = State()
    expense = State()
    receipt = State()


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

    if project.expenses:
        lines.append("")
        lines.append("<b>Закупки на свои</b>")
        for e in sorted(project.expenses, key=lambda x: x.created_at):
            when = e.created_at.strftime("%d.%m")
            note = f" — {e.comment}" if e.comment else ""
            paper = " 🧾" if e.receipt else ""
            lines.append(f"• {when}: {money(e.amount)}{note}{paper}")
        lines.append(f"\nЗакупил на: <b>{money(project.spent)}</b>")

    if project.deal_amount or project.spent:
        lines.append("")
        if project.due > 0:
            tail = " (работа + закупки)" if project.spent else ""
            lines.append(f"Остаток с заказчика: <b>{money(project.due)}</b>{tail}")
        elif project.paid > project.deal_amount + project.spent:
            over = project.paid - project.deal_amount - project.spent
            lines.append(f"Переплата: <b>{money(over)}</b>")
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


# --- закупки мастера на свои -------------------------------------------------


@router.callback_query(F.data.startswith("addexp:"))
async def ask_expense(call: CallbackQuery, state: FSMContext) -> None:
    """Мастер купил материалы на свои — заказчик вернёт деньги по чеку.

    Позиции не спрашиваем: Саня на объекте, с телефона в руках; сумма и «что взял»
    одной строкой — это он напишет, а таблицу позиций набивать не станет.
    """
    project_id = int(call.data.split(":")[1])
    await state.update_data(project_id=project_id)
    await state.set_state(Money.expense)
    await call.answer()
    await call.message.answer(
        "Сколько потратил и на что?\n\n"
        "<code>12400 клей 6 мешков, затирка</code>\n"
        "<code>6000 грунтовка и СВП</code>\n\n"
        "<i>Можно просто сумму. Дальше пришлёшь фото чека — или пропустишь.</i>"
    )


@router.message(Money.expense)
async def add_expense(message: Message, state: FSMContext, storage: Storage) -> None:
    try:
        amount, comment = amount_and_comment(message.text or "")
    except ParseError as e:
        await message.answer(f"{e}\n\nПример: <code>12400 клей и затирка</code>")
        return
    if amount > 100_000_000:  # промах по нулю на телефоне уехал бы в долг заказчика
        await message.answer("Столько за раз не закупают — проверь сумму.")
        return

    data = await state.get_data()
    expense_id = await storage.add_expense(
        data["project_id"], message.from_user.id, amount, comment
    )
    if expense_id is None:
        await state.clear()
        await message.answer("Объект не найден.", reply_markup=kb.MAIN_MENU)
        return

    await state.clear()
    head = f"Записал закупку: <b>{money(amount)}</b>" + (f" — {comment}" if comment else "")
    project = await storage.get_project(data["project_id"], message.from_user.id)
    # Ждать фото «просто так» нельзя: пока бот в этом состоянии, кнопки меню мертвы,
    # а случайное фото (плитки, объекта) прилипло бы чеком. Поэтому чек — по кнопке.
    await message.answer(
        f"{head}\n\n{_card(project)}", reply_markup=kb.money_actions(project.id, expense_id)
    )


@router.callback_query(F.data.startswith("addreceipt:"))
async def ask_receipt(call: CallbackQuery, state: FSMContext) -> None:
    expense_id = int(call.data.split(":")[1])
    await state.update_data(expense_id=expense_id)
    await state.set_state(Money.receipt)
    await call.answer()
    await call.message.answer(
        "Пришли <b>фото чека</b> — покажешь его заказчику.\n\n"
        "<i>Передумал — /cancel, закупка уже записана.</i>"
    )


@router.message(Money.receipt, F.photo)
async def save_receipt(message: Message, state: FSMContext, storage: Storage) -> None:
    data = await state.get_data()
    # Самый крупный размер: чек надо будет читать глазами, превью не годится.
    file = await message.bot.get_file(message.photo[-1].file_id)
    buf = await message.bot.download_file(file.file_path)
    expense = await storage.get_expense(data["expense_id"], message.from_user.id)
    if expense is None:  # закупку успели удалить, пока мастер искал чек
        await state.clear()
        await message.answer("Этой закупки уже нет.", reply_markup=kb.MAIN_MENU)
        return

    name = receipts.save(expense.id, buf.read())
    await storage.set_expense_receipt(expense.id, message.from_user.id, name)

    await state.clear()
    project = await storage.get_project(expense.project_id, message.from_user.id)
    await message.answer(
        f"Чек сохранил.\n\n{_card(project)}", reply_markup=kb.money_actions(project.id)
    )


