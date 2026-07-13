"""Объекты: сводка закупки и смета заказчику.

Сводка — главное, ради чего объект вообще хранится: посчитал стены по одной, а
купить надо одним списком.
"""

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from tilebot.bot import keyboards as kb
from tilebot.core.estimate import build_estimate, format_estimate, money
from tilebot.core.layout import Layout, build_layout
from tilebot.core.materials import Materials, calc_materials, merge_materials
from tilebot.render.pdf import render_estimate_pdf
from tilebot.render.scheme import render_layout
from tilebot.storage import Project, Storage, payload_to_surface

router = Router(name="projects")
logger = logging.getLogger(__name__)

# Чужой объект и несуществующий для мастера — одно и то же: не подсказываем, что
# объект с таким номером вообще есть.
NOT_YOURS = "Объект не найден."


def _rebuild(project: Project) -> tuple[list[Layout], list[Materials], bool]:
    """Пересобрать раскладки объекта из сохранённых замеров."""
    layouts: list[Layout] = []
    materials: list[Materials] = []
    waterproofing = False

    for row in project.surfaces:
        surface, tile, pattern, start_from, wp = payload_to_surface(row.dump())
        layout = build_layout(surface, tile, pattern, start_from)
        layouts.append(layout)
        materials.append(calc_materials(layout, waterproofing=wp))
        waterproofing = waterproofing or wp

    return layouts, materials, waterproofing


@router.message(F.text == "📋 Мои объекты")
async def my_projects(message: Message, storage: Storage) -> None:
    projects = await storage.list_projects(message.from_user.id)
    if not projects:
        await message.answer(
            "Объектов пока нет. Нажми <b>🧱 Плитка</b> — посчитаем первый.",
            reply_markup=kb.MAIN_MENU,
        )
        return

    await message.answer(
        "<b>Твои объекты</b>\n<i>В скобках — сколько поверхностей посчитано.</i>",
        reply_markup=kb.projects_list(projects),
    )


@router.callback_query(F.data.startswith("open:"))
async def open_project(call: CallbackQuery, storage: Storage) -> None:
    project_id = int(call.data.split(":")[1])
    project = await storage.get_project(project_id, call.from_user.id)
    await call.answer()
    if not project:
        await call.message.answer(NOT_YOURS)
        return

    lines = [f"<b>{project.title}</b>", f"Поверхностей: {len(project.surfaces)}"]
    if project.photos:
        lines.append(f"Фото: {len(project.photos)}")
    if project.deal_amount:
        lines.append(f"Договор: {money(project.deal_amount)} · получено {money(project.paid)}")
        if project.due > 0:
            lines.append(f"<b>Остаток с заказчика: {money(project.due)}</b>")
        else:
            lines.append("✅ Рассчитались")

    await call.message.answer("\n".join(lines), reply_markup=kb.project_actions(project_id))


@router.callback_query(F.data.startswith("summary:"))
async def summary(call: CallbackQuery, storage: Storage) -> None:
    project_id = int(call.data.split(":")[1])
    project = await storage.get_project(project_id, call.from_user.id)
    await call.answer()
    if not project:
        await call.message.answer(NOT_YOURS)
        return
    if not project.surfaces:
        await call.message.answer("В объекте пока нет поверхностей.")
        return

    layouts, materials, _ = _rebuild(project)
    total_area = sum(lay.surface.net_area_m2 for lay in layouts)
    total_tiles = sum(m.tiles_count for m in materials)

    lines = [f"<b>{project.title}</b> — итог по объекту", ""]
    for lay in layouts:
        lines.append(
            f"• {lay.surface.name}: {lay.surface.net_area_m2:.2f} м², "
            f"плитка {lay.tile.width_mm:.0f}×{lay.tile.height_mm:.0f}, {lay.tiles_grid} шт"
        )

    lines += [
        "",
        f"<b>Всего площадь: {total_area:.2f} м²</b>",
        f"Плитки с запасом: {total_tiles} шт",
        "",
        "<b>Купить на объект:</b>",
    ]
    for line in merge_materials(materials):
        note = f" <i>({line.note})</i>" if line.note else ""
        lines.append(f"• {line.name}: <b>{line.format_qty()} {line.unit}</b>{note}")

    tile_cost = sum(
        m.tile_area_with_waste_m2 * lay.tile.price_per_m2
        for lay, m in zip(layouts, materials, strict=True)
        if lay.tile.price_per_m2
    )
    if tile_cost:
        lines += ["", f"Плитка обойдётся в <b>{money(tile_cost)}</b>"]

    await call.message.answer("\n".join(lines), reply_markup=kb.project_actions(project_id))


@router.callback_query(F.data.startswith("estimate:"))
async def estimate(call: CallbackQuery, storage: Storage, state: FSMContext) -> None:
    project_id = int(call.data.split(":")[1])
    project = await storage.get_project(project_id, call.from_user.id)
    await call.answer()
    if not project:
        await call.message.answer(NOT_YOURS)
        return
    if not project.surfaces:
        await call.message.answer("В объекте пока нет поверхностей.")
        return

    user = await storage.get_or_create_user(call.from_user.id)
    layouts, materials, waterproofing = _rebuild(project)

    est = build_estimate(
        project.title,
        layouts,
        materials,
        user.price,
        waterproofing=waterproofing,
    )

    await call.message.answer(format_estimate(est))

    pdf = render_estimate_pdf(
        est,
        master_name=user.name,
        master_phone=user.phone,
        schemes=[render_layout(lay) for lay in layouts],
    )
    safe_title = "".join(c for c in project.title if c.isalnum() or c in " -_")[:40].strip()
    await call.message.answer_document(
        BufferedInputFile(pdf, filename=f"Смета — {safe_title or 'объект'}.pdf"),
        caption="Смета со схемами раскладки — можно переслать заказчику.",
    )


@router.callback_query(F.data.startswith("delete:"))
async def delete_project(call: CallbackQuery, storage: Storage) -> None:
    project_id = int(call.data.split(":")[1])
    deleted = await storage.delete_project(project_id, call.from_user.id)
    await call.answer("Удалил" if deleted else "Объект не найден")
    await call.message.answer(
        "Объект удалён." if deleted else NOT_YOURS, reply_markup=kb.MAIN_MENU
    )
