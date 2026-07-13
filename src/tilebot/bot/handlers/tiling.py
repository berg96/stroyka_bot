"""Основной сценарий: объект → поверхность → плитка → схема, материалы, советы."""

import logging

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from tilebot.bot import keyboards as kb
from tilebot.bot.parse import ParseError, dimensions, name_and_numbers, numbers, to_mm
from tilebot.core.estimate import money
from tilebot.core.layout import Layout, best_orientation
from tilebot.core.materials import Materials, calc_materials
from tilebot.core.models import LayoutPattern, Opening, StartFrom, Surface, SurfaceKind, Tile
from tilebot.render.scheme import render_layout
from tilebot.storage import Storage, surface_to_payload

router = Router(name="tiling")
logger = logging.getLogger(__name__)


class Tiling(StatesGroup):
    project_title = State()
    surface_kind = State()
    surface_size = State()
    openings = State()
    tile_size = State()
    tile_details = State()
    pattern = State()
    start_from = State()
    waterproofing = State()


@router.message(F.text == "🧱 Плитка")
async def start_tiling(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(Tiling.project_title)
    await message.answer(
        "Как назовём объект?\n\n<i>Например: «Ванная, Борзова 12» — чтобы потом найти.</i>"
    )


@router.message(Tiling.project_title)
async def got_title(message: Message, state: FSMContext, storage: Storage) -> None:
    title = (message.text or "").strip()[:128]
    if not title:
        await message.answer("Напиши название объекта.")
        return

    project = await storage.create_project(message.from_user.id, title)
    await state.update_data(project_id=project.id, surface_no=0)
    await _ask_surface_kind(message, state)


async def _ask_surface_kind(message: Message, state: FSMContext) -> None:
    await state.set_state(Tiling.surface_kind)
    data = await state.get_data()
    n = data.get("surface_no", 0) + 1
    await message.answer(f"<b>Поверхность {n}</b>. Что считаем?", reply_markup=kb.SURFACE_KIND)


@router.callback_query(F.data.startswith("add_surface:"))
async def add_surface(call: CallbackQuery, state: FSMContext) -> None:
    project_id = int(call.data.split(":")[1])
    data = await state.get_data()
    await state.set_data(
        {"project_id": project_id, "surface_no": data.get("surface_no", 0)}
    )
    await call.answer()
    await _ask_surface_kind(call.message, state)


@router.callback_query(Tiling.surface_kind, F.data.startswith("kind:"))
async def got_kind(call: CallbackQuery, state: FSMContext) -> None:
    kind = SurfaceKind.WALL if call.data.endswith("wall") else SurfaceKind.FLOOR
    await state.update_data(kind=kind.value)
    await state.set_state(Tiling.surface_size)
    await call.answer()

    if kind is SurfaceKind.WALL:
        prompt = (
            "Размер стены — <b>ширина и высота</b>:\n\n"
            "<code>2.7 2.5</code>  или  <code>2700 2500</code>\n"
            "<i>Понимаю и метры, и миллиметры.</i>"
        )
    else:
        prompt = (
            "Размер пола — <b>длина и ширина</b>:\n\n"
            "<code>2.7 1.7</code>  или  <code>2700 1700</code>"
        )
    await call.message.answer(prompt)


@router.message(Tiling.surface_size)
async def got_size(message: Message, state: FSMContext) -> None:
    try:
        width, height = dimensions(message.text or "", count=2)
    except ParseError as e:
        await message.answer(f"{e}\n\nНапиши два числа через пробел: <code>2.7 2.5</code>")
        return

    await state.update_data(width_mm=width, height_mm=height)
    await state.set_state(Tiling.openings)
    data = await state.get_data()
    what = "дверь, окно, короб" if data["kind"] == "wall" else "короб, ванна"
    await message.answer(
        f"Есть что вычесть ({what})?\n\n"
        "Пиши размерами: <code>дверь 0.8 2.1</code>\n"
        "Несколько — с новой строки. Если знаешь, где именно, добавь отступ слева и снизу: "
        "<code>дверь 0.8 2.1 от 1.9 0</code>\n\n"
        "<i>С координатами я не посчитаю плитку, которая уходит в проём, — точнее выйдет.</i>",
        reply_markup=kb.SKIP,
    )


def _parse_openings(text: str) -> list[Opening]:
    """Строки вида «дверь 0.8 2.1» или «дверь 0.8 2.1 от 1.9 0»."""
    openings: list[Opening] = []
    for raw in text.strip().splitlines():
        line = raw.strip()
        if not line:
            continue

        name, values = name_and_numbers(line.replace("от", " "))
        name = name or "проём"
        if len(values) not in (2, 4):
            raise ParseError(
                f"«{line}» — нужно 2 числа (ширина высота) или 4 (ширина высота от X Y)."
            )
        if values[0] <= 0 or values[1] <= 0:
            raise ParseError(f"«{line}» — размеры проёма должны быть больше нуля.")
        if len(values) == 4 and (values[2] < 0 or values[3] < 0):
            raise ParseError(f"«{line}» — отступ не может быть отрицательным.")

        # Координаты необязательны: без них проём вычтется из площади, но плитку
        # под ним мы не выбросим — не знаем, какую именно. Ноль здесь нормален:
        # дверь стоит прямо на полу.
        x, y = (to_mm(values[2]), to_mm(values[3])) if len(values) == 4 else (None, None)
        openings.append(
            Opening(
                name=name[:24],
                width_mm=to_mm(values[0]),
                height_mm=to_mm(values[1]),
                x_mm=x,
                y_mm=y,
            )
        )
    return openings


@router.message(Tiling.openings)
async def got_openings(message: Message, state: FSMContext) -> None:
    try:
        openings = _parse_openings(message.text or "")
    except ParseError as e:
        await message.answer(f"{e}\n\nПример: <code>дверь 0.8 2.1</code>", reply_markup=kb.SKIP)
        return

    await state.update_data(
        openings=[
            {
                "name": o.name,
                "width_mm": o.width_mm,
                "height_mm": o.height_mm,
                "x_mm": o.x_mm,
                "y_mm": o.y_mm,
            }
            for o in openings
        ]
    )
    await _ask_tile(message, state)


@router.callback_query(Tiling.openings, F.data == "skip")
async def skip_openings(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(openings=[])
    await call.answer()
    await _ask_tile(call.message, state)


async def _ask_tile(message: Message, state: FSMContext) -> None:
    await state.set_state(Tiling.tile_size)
    await message.answer(
        "Размер плитки — <b>ширина и высота</b>:\n\n"
        "<code>60 30</code> (см)  или  <code>600 300</code> (мм)\n"
        "<i>Как класть — вдоль или поперёк — подскажу сам.</i>"
    )


@router.message(Tiling.tile_size)
async def got_tile_size(message: Message, state: FSMContext) -> None:
    try:
        values = numbers(message.text or "")
    except ParseError as e:
        await message.answer(f"{e}\n\nПример: <code>60 30</code>")
        return
    if len(values) != 2:
        await message.answer("Нужно два числа: <code>60 30</code>")
        return
    if values[0] <= 0 or values[1] <= 0:
        await message.answer("Размер плитки должен быть больше нуля: <code>60 30</code>")
        return

    # Плитку меряют в сантиметрах («шестьдесят на тридцать»), но пишут и в мм.
    def tile_mm(v: float) -> float:
        return v * 10 if v < 200 else v

    await state.update_data(tile_w=tile_mm(values[0]), tile_h=tile_mm(values[1]))
    await state.set_state(Tiling.tile_details)
    await message.answer(
        "Шов, толщина плитки, штук в упаковке, цена за м² — через пробел:\n\n"
        "<code>2 9 8 1450</code>\n"
        "<i>Что не знаешь — ставь 0. Можно просто <code>2</code> — остальное по умолчанию.</i>"
    )


@router.message(Tiling.tile_details)
async def got_tile_details(message: Message, state: FSMContext) -> None:
    try:
        values = numbers(message.text or "")
    except ParseError as e:
        await message.answer(f"{e}\n\nПример: <code>2 9 8 1450</code>")
        return

    joint = values[0] if values else 2.0
    thickness = values[1] if len(values) > 1 and values[1] else 9.0
    per_pack = int(values[2]) if len(values) > 2 and values[2] else None
    price = values[3] if len(values) > 3 and values[3] else None

    await state.update_data(
        joint_mm=joint, thickness_mm=thickness, per_pack=per_pack, price_per_m2=price
    )
    await state.set_state(Tiling.pattern)
    await message.answer("Как кладём?", reply_markup=kb.PATTERNS)


@router.callback_query(Tiling.pattern, F.data.startswith("pat:"))
async def got_pattern(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(pattern=call.data.split(":", 1)[1])
    await state.set_state(Tiling.start_from)
    await call.answer()
    await call.message.answer(
        "Откуда начинаем ряд?\n\n"
        "<i>От угла — целая плитка в углу, вся подрезка уходит в другой край. "
        "От центра — подрезка делится поровну на два края, смотрится аккуратнее.</i>",
        reply_markup=kb.START_FROM,
    )


@router.callback_query(Tiling.start_from, F.data.startswith("start:"))
async def got_start(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(start_from=call.data.split(":", 1)[1])
    await state.set_state(Tiling.waterproofing)
    await call.answer()
    await call.message.answer("Гидроизоляция нужна?", reply_markup=kb.YES_NO_WATERPROOF)


@router.callback_query(Tiling.waterproofing, F.data.startswith("wp:"))
async def got_waterproofing(
    call: CallbackQuery, state: FSMContext, storage: Storage
) -> None:
    waterproofing = call.data.endswith("1")
    await call.answer()
    data = await state.get_data()

    surface = Surface(
        name=("Стена" if data["kind"] == "wall" else "Пол") + f" {data.get('surface_no', 0) + 1}",
        width_mm=data["width_mm"],
        height_mm=data["height_mm"],
        kind=SurfaceKind(data["kind"]),
        openings=[Opening(**o) for o in data.get("openings", [])],
    )
    tile = Tile(
        width_mm=data["tile_w"],
        height_mm=data["tile_h"],
        thickness_mm=data["thickness_mm"],
        joint_mm=data["joint_mm"],
        per_pack=data.get("per_pack"),
        price_per_m2=data.get("price_per_m2"),
    )
    pattern = LayoutPattern(data["pattern"])
    start_raw = data["start_from"]

    if start_raw == "auto":
        # «Реши сам» — перебираем оба старта и обе ориентации плитки.
        candidates = [
            best_orientation(surface, tile, pattern, StartFrom.EDGE)[0],
            best_orientation(surface, tile, pattern, StartFrom.CENTER)[0],
        ]
        layout = max(candidates, key=lambda lay: min(lay.x.min_cut_mm, lay.y.min_cut_mm))
    else:
        start_from = StartFrom(start_raw)
        layout, _ = best_orientation(surface, tile, pattern, start_from)

    materials = calc_materials(layout, waterproofing=waterproofing)

    await storage.add_surface(
        data["project_id"],
        surface_to_payload(
            layout.surface,
            layout.tile,
            layout.pattern,
            layout.start_from,
            waterproofing=waterproofing,
        ),
    )
    await state.update_data(surface_no=data.get("surface_no", 0) + 1)
    await state.set_state(None)

    png = render_layout(layout, title=f"{surface.name} — {data.get('title', '')}".strip(" —"))
    await call.message.answer_photo(
        BufferedInputFile(png, filename="scheme.png"),
        caption=_surface_caption(layout, materials),
        reply_markup=kb.after_surface(data["project_id"]),
    )


def _surface_caption(layout: Layout, materials: Materials) -> str:
    tile = layout.tile
    lines = [
        f"<b>{layout.surface.name}</b> — {layout.surface.net_area_m2:.2f} м²",
        f"Плитка {tile.width_mm:.0f}×{tile.height_mm:.0f}, шов {tile.joint_mm:.0f} мм",
        f"Класть: <b>{layout.tiles_grid} шт</b> (резаных {layout.cuts_count})",
        "",
        "<b>Купить:</b>",
    ]
    for line in materials.lines:
        note = f" <i>({line.note})</i>" if line.note else ""
        lines.append(f"• {line.name}: <b>{line.format_qty()} {line.unit}</b>{note}")

    if tile.price_per_m2:
        cost = materials.tile_area_with_waste_m2 * tile.price_per_m2
        lines.append(f"\nПлитка на {money(cost)}")

    lines.append("")
    for advice in layout.advice:
        lines.append(f"💡 {advice}")

    return "\n".join(lines)


@router.message(StateFilter(None), F.text.regexp(r"^\d"))
async def stray_numbers(message: Message) -> None:
    """Мастер прислал числа, не начав расчёт — подскажем, куда нажать."""
    await message.answer(
        "Чтобы посчитать, нажми <b>🧱 Плитка</b> или <b>📐 Площадь</b>.",
        reply_markup=kb.MAIN_MENU,
    )
