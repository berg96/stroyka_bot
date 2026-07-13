"""Фото объекта: основание «до», процесс, результат.

Типовой спор — «плитка отвалилась, мастер виноват», хотя основание было сырое или
сыпучее. Фото до начала работ с датой закрывает вопрос. Плюс готовое портфолио,
чтобы показывать новым заказчикам.

Файлы не качаем: Telegram хранит их сам, нам достаточно file_id.
"""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InputMediaPhoto, Message

from tilebot.bot import keyboards as kb
from tilebot.storage import Storage

router = Router(name="photos")

MEDIA_GROUP_LIMIT = 10  # Telegram не отдаёт альбом больше десяти


class Photos(StatesGroup):
    waiting = State()


@router.callback_query(F.data.startswith("addphoto:"))
async def ask_photo(call: CallbackQuery, state: FSMContext) -> None:
    project_id = int(call.data.split(":")[1])
    await state.update_data(project_id=project_id)
    await state.set_state(Photos.waiting)
    await call.answer()
    await call.message.answer(
        "Пришли фото — можно несколько подряд, с подписью.\n\n"
        "<i>Снимай основание до работ: если потом прилетит «плитка отходит», "
        "будет чем ответить. Готовую работу — тоже, пригодится показывать заказчикам.</i>\n\n"
        "Как закончишь — /cancel или жми любую кнопку меню."
    )


@router.message(Photos.waiting, F.photo)
async def save_photo(message: Message, state: FSMContext, storage: Storage) -> None:
    data = await state.get_data()
    project_id = data["project_id"]

    # Берём самый крупный размер — Telegram отдаёт лесенку превью.
    file_id = message.photo[-1].file_id
    saved = await storage.add_photo(
        project_id, message.from_user.id, file_id, message.caption or ""
    )
    if not saved:
        await state.clear()
        await message.answer("Объект не найден.", reply_markup=kb.MAIN_MENU)
        return

    project = await storage.get_project(project_id, message.from_user.id)
    await message.answer(
        f"Сохранил в «{project.title}». Фото в объекте: <b>{len(project.photos)}</b>.\n"
        "<i>Шли ещё или /cancel.</i>"
    )


@router.message(Photos.waiting, ~F.photo)
async def not_a_photo(message: Message) -> None:
    await message.answer("Жду фото. Или /cancel, если передумал.")


@router.callback_query(F.data.startswith("photos:"))
async def show_photos(call: CallbackQuery, storage: Storage) -> None:
    project_id = int(call.data.split(":")[1])
    project = await storage.get_project(project_id, call.from_user.id)
    await call.answer()

    if not project or not project.photos:
        await call.message.answer(
            "Фото по объекту нет.", reply_markup=kb.project_actions(project_id)
        )
        return

    photos = sorted(project.photos, key=lambda p: p.created_at)
    await call.message.answer(f"<b>{project.title}</b> — фото: {len(photos)}")

    for start in range(0, len(photos), MEDIA_GROUP_LIMIT):
        chunk = photos[start : start + MEDIA_GROUP_LIMIT]
        media = [
            InputMediaPhoto(
                media=p.file_id,
                caption=f"{p.created_at.strftime('%d.%m.%Y')}"
                + (f" — {p.caption}" if p.caption else ""),
            )
            for p in chunk
        ]
        await call.message.answer_media_group(media)

    await call.message.answer("Что дальше?", reply_markup=kb.project_actions(project_id))
