"""Основной сценарий: объект → поверхности → плитка → схемы, материалы, советы.

Мастер меряет комнату целиком, а не стену за стеной: в ванной четыре стены кладут
одной плиткой, и закупка нужна одна. Поэтому «Комната целиком» спрашивает стены по
кругу и высоту, а параметры плитки — один раз на всю комнату.
"""

import io
import logging
from dataclasses import replace

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, InputMediaPhoto, Message
from PIL import Image
from PIL.Image import Image as PilImage

from tilebot.bot import keyboards as kb
from tilebot.bot.parse import (
    ParseError,
    dimensions,
    meters,
    name_and_numbers,
    numbers,
    single_number,
    to_mm,
)
from tilebot.core.estimate import money
from tilebot.core.layout import Layout
from tilebot.core.models import (
    BRICK_OFFSETS,
    DEFAULT_OFFSET,
    WASTE_BY_PATTERN,
    LayoutPattern,
    Opening,
    SavedSurface,
    StartFrom,
    Surface,
    SurfaceKind,
    Tile,
)
from tilebot.core.project import ProjectResult, Savings, compute_project
from tilebot.core.room import floor_dims, room_surfaces
from tilebot.core.units import fmt_mm, plural
from tilebot.core.wrap import supports_wrap
from tilebot.render.scheme import render_layout
from tilebot.storage import Storage, payload_to_surface, surface_to_payload

router = Router(name="tiling")
logger = logging.getLogger(__name__)

class Tiling(StatesGroup):
    project_title = State()
    room_walls = State()
    room_height = State()
    surface_kind = State()
    surface_size = State()
    tile_size = State()
    joint_custom = State()
    thickness = State()
    price = State()
    per_pack = State()
    opening_size = State()
    tile_photo = State()
    floor_tile_size = State()
    floor_per_pack = State()
    resize = State()


@router.message(F.text == "🧱 Плитка")
async def start_tiling(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Что считаем?", reply_markup=kb.TILING_MODE)


@router.callback_query(F.data.startswith("mode:"))
async def pick_mode(call: CallbackQuery, state: FSMContext) -> None:
    mode = call.data.split(":", 1)[1]
    await state.clear()
    await state.update_data(mode=mode)
    await state.set_state(Tiling.project_title)
    await call.answer()
    await call.message.answer(
        "Как назовём объект?\n\n<i>Например: «Ванная, Борзова 12» — чтобы потом найти.</i>"
    )


@router.message(Tiling.project_title)
async def got_title(message: Message, state: FSMContext, storage: Storage) -> None:
    title = (message.text or "").strip()[:128]
    if not title:
        await message.answer("Напиши название объекта.")
        return

    project = await storage.create_project(message.from_user.id, title)
    data = await state.get_data()
    await state.update_data(project_id=project.id, title=title, surface_no=0)

    if data.get("mode") == "room":
        await state.set_state(Tiling.room_walls)
        await message.answer(
            "Обмерь комнату <b>по кругу</b> — длина каждой стены через пробел:\n\n"
            "<code>2 1.8 2 1.8</code>\n\n"
            "<i>Сколько стен — столько чисел. Высоту спрошу отдельно, "
            "плитку и шов — один раз на всю комнату.</i>"
        )
    else:
        await _ask_surface_kind(message, state)


# --- Комната целиком ---------------------------------------------------------


@router.message(Tiling.room_walls)
async def got_room_walls(message: Message, state: FSMContext) -> None:
    try:
        walls = meters(message.text or "")
    except ParseError as e:
        await message.answer(f"{e}\n\nПример: <code>2 1.8 2 1.8</code>")
        return

    if len(walls) < 2:
        await message.answer("Нужно хотя бы две стены: <code>2 1.8 2 1.8</code>")
        return

    await state.update_data(walls=walls)
    await state.set_state(Tiling.room_height)
    await message.answer(
        f"Стен: <b>{len(walls)}</b>, периметр {sum(walls):.2f} м.\n\n"
        "Теперь <b>высота</b> — до потолка или докуда кладём плитку:\n\n"
        "<code>2.7</code>"
    )


# Высота, при которой замер точно перепутан с единицами: «270» — это 2,7 м в
# сантиметрах, а по общему правилу вышло бы 27 см. Молча считать такое нельзя.
MIN_HEIGHT_M = 1.0
MAX_HEIGHT_M = 6.0


@router.message(Tiling.room_height)
async def got_room_height(message: Message, state: FSMContext) -> None:
    try:
        (height_m,) = meters(message.text or "", count=1)
    except ParseError as e:
        await message.answer(f"{e}\n\nПример: <code>2.7</code>")
        return

    if not MIN_HEIGHT_M <= height_m <= MAX_HEIGHT_M:
        await message.answer(
            f"Высота {height_m:.2f} м — это точно так? Похоже, единицы перепутаны.\n\n"
            "Напиши в метрах (<code>2.7</code>) или в миллиметрах (<code>2700</code>)."
        )
        return

    data = await state.get_data()
    walls = data["walls"]

    await state.update_data(height_m=height_m)

    # Пол предлагаем только там, где его можно посчитать по стенам: у прямоугольной
    # комнаты. Кривую пусть меряет через «📐 Площадь» — врать площадью не будем.
    if len(walls) == 4 and floor_dims(walls) is not None:
        await message.answer("Пол тоже плиткой?", reply_markup=kb.ROOM_FLOOR)
        return

    await state.update_data(with_floor=False)
    await _ask_tile(message, state)


@router.callback_query(F.data.startswith("floor:"))
async def got_room_floor(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(with_floor=call.data.endswith("1"))
    await call.answer()
    await _ask_tile(call.message, state)


# --- Одна поверхность --------------------------------------------------------


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
        {
            "project_id": project_id,
            "surface_no": data.get("surface_no", 0),
            "title": data.get("title", ""),
            "mode": "single",
        }
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
    await _ask_tile(message, state)


# --- Плитка: размер, шов, толщина, цена --------------------------------------


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

    await state.update_data(tile_w=_tile_mm(values[0]), tile_h=_tile_mm(values[1]))
    await _ask_joint(message, state)


def _tile_mm(value: float) -> float:
    """Плитку меряют в сантиметрах («шестьдесят на тридцать»), но пишут и в мм."""
    return value * 10 if value < 200 else value


async def _ask_joint(message: Message, state: FSMContext) -> None:
    # Состояние держим на «своём размере»: мастер может ткнуть кнопку, а может
    # сразу написать «1,4» — и то, и другое должно сработать.
    await state.set_state(Tiling.joint_custom)
    await message.answer(
        "Какой шов?\n\n<i>Или напиши свой: <code>1,4</code></i>", reply_markup=kb.JOINTS
    )


@router.callback_query(F.data.startswith("joint:"))
async def got_joint(call: CallbackQuery, state: FSMContext) -> None:
    raw = call.data.split(":", 1)[1]
    await call.answer()

    if raw == "custom":
        await state.set_state(Tiling.joint_custom)
        await call.message.answer(
            "Толщина шва в миллиметрах:\n\n<code>1.4</code>\n"
            "<i>Можно с запятой — 1,4 так и посчитаю, не округлю.</i>"
        )
        return

    await _joint_done(call.message, state, float(raw))


@router.message(Tiling.joint_custom)
async def got_joint_custom(message: Message, state: FSMContext) -> None:
    try:
        joint = single_number(message.text or "", minimum=0.1, maximum=20)
    except ParseError as e:
        await message.answer(f"{e}\n\nПример: <code>1.4</code>", reply_markup=kb.JOINTS)
        return

    await _joint_done(message, state, joint)


async def _joint_done(message: Message, state: FSMContext, joint: float) -> None:
    await state.update_data(joint_mm=joint)
    await state.set_state(Tiling.thickness)
    await message.answer(
        f"Шов <b>{fmt_mm(joint)} мм</b>. Толщина плитки?\n\n"
        "<i>Или напиши свою: <code>12</code></i>",
        reply_markup=kb.THICKNESS,
    )


@router.callback_query(F.data.startswith("thick:"))
async def got_thickness(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await _thickness_done(call.message, state, float(call.data.split(":", 1)[1]))


@router.message(Tiling.thickness)
async def got_thickness_custom(message: Message, state: FSMContext) -> None:
    try:
        thickness = single_number(message.text or "", minimum=1, maximum=50)
    except ParseError as e:
        await message.answer(f"{e}\n\nПример: <code>12</code>", reply_markup=kb.THICKNESS)
        return

    await _thickness_done(message, state, thickness)


async def _thickness_done(message: Message, state: FSMContext, thickness: float) -> None:
    # Цену плитки здесь не спрашиваем: мастер продаёт работу, а плитку заказчик
    # покупает сам по списку. Посчитать материалы в деньгах можно потом кнопкой —
    # это нужно, только если мастер закупается сам.
    await state.update_data(thickness_mm=thickness)
    await _ask_per_pack(message, state)


async def _ask_per_pack(message: Message, state: FSMContext) -> None:
    await state.set_state(Tiling.per_pack)
    await message.answer(
        "Штук в упаковке — тогда посчитаю, сколько пачек брать:\n\n<code>8</code>",
        reply_markup=kb.SKIP,
    )


@router.message(Tiling.per_pack)
async def got_per_pack(message: Message, state: FSMContext) -> None:
    try:
        per_pack = single_number(message.text or "", minimum=0)
    except ParseError as e:
        await message.answer(f"{e}\n\nПример: <code>8</code>", reply_markup=kb.SKIP)
        return

    await state.update_data(per_pack=int(per_pack) or None)
    await _after_tile(message, state)


@router.callback_query(Tiling.per_pack, F.data == "skip")
async def skip_per_pack(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(per_pack=None)
    await call.answer()
    await _after_tile(call.message, state)


# --- Плитка на пол: своя ------------------------------------------------------


async def _after_tile(message: Message, state: FSMContext) -> None:
    """На пол почти всегда идёт другая плитка — керамогранит крупнее настенной."""
    data = await state.get_data()
    if data.get("mode") == "room" and data.get("with_floor"):
        await state.set_state(Tiling.floor_tile_size)
        await message.answer(
            "Плитка <b>на пол</b> — ширина и высота:\n\n"
            "<code>60 60</code>\n"
            "<i>На пол обычно кладут другую — крупнее настенной. Если та же самая, "
            "жми кнопку.</i>",
            reply_markup=kb.SAME_TILE,
        )
        return
    await _ask_pattern(message, state)


@router.message(Tiling.floor_tile_size)
async def got_floor_tile(message: Message, state: FSMContext) -> None:
    try:
        values = numbers(message.text or "")
    except ParseError as e:
        await message.answer(f"{e}\n\nПример: <code>60 60</code>", reply_markup=kb.SAME_TILE)
        return
    if len(values) != 2 or values[0] <= 0 or values[1] <= 0:
        await message.answer("Нужно два числа: <code>60 60</code>", reply_markup=kb.SAME_TILE)
        return

    await state.update_data(floor_w=_tile_mm(values[0]), floor_h=_tile_mm(values[1]))
    await state.set_state(Tiling.floor_per_pack)
    await message.answer(
        "Штук в упаковке <b>напольной</b> плитки:\n\n<code>4</code>",
        reply_markup=kb.SKIP,
    )


@router.callback_query(Tiling.floor_tile_size, F.data == "same_tile")
async def floor_same_tile(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(floor_w=None, floor_h=None)
    await call.answer()
    await _ask_pattern(call.message, state)


@router.message(Tiling.floor_per_pack)
async def got_floor_per_pack(message: Message, state: FSMContext) -> None:
    try:
        per_pack = single_number(message.text or "", minimum=0)
    except ParseError as e:
        await message.answer(f"{e}\n\nПример: <code>4</code>", reply_markup=kb.SKIP)
        return

    await state.update_data(floor_per_pack=int(per_pack) or None)
    await _ask_pattern(message, state)


@router.callback_query(Tiling.floor_per_pack, F.data == "skip")
async def skip_floor_per_pack(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(floor_per_pack=None)
    await call.answer()
    await _ask_pattern(call.message, state)


# --- Раскладка, запас, гидроизоляция -----------------------------------------


async def _ask_pattern(message: Message, state: FSMContext) -> None:
    await state.set_state(None)
    await message.answer("Как кладём?", reply_markup=kb.PATTERNS)


@router.callback_query(F.data.startswith("pat:"))
async def got_pattern(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(pattern=call.data.split(":", 1)[1])
    await call.answer()
    await call.message.answer(
        "Откуда начинаем ряд?\n\n"
        "<i>От угла — целая плитка в углу, вся подрезка уходит в другой край. "
        "От центра — подрезка делится поровну на два края, смотрится аккуратнее.</i>",
        reply_markup=kb.START_FROM,
    )


@router.callback_query(F.data.startswith("start:"))
async def got_start(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(start_from=call.data.split(":", 1)[1])
    await call.answer()

    data = await state.get_data()
    suggested = round(WASTE_BY_PATTERN[LayoutPattern(data["pattern"])] * 100)
    await call.message.answer(
        f"Запас плитки на бой и подрезку? <i>Под эту раскладку советую {suggested}%.</i>",
        reply_markup=kb.waste_options(suggested),
    )


@router.callback_query(F.data.startswith("waste:"))
async def got_waste(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(waste=int(call.data.split(":", 1)[1]) / 100)
    await call.answer()
    await call.message.answer("Гидроизоляция нужна?", reply_markup=kb.YES_NO_WATERPROOF)


@router.callback_query(F.data.startswith("wp:"))
async def got_waterproofing(call: CallbackQuery, state: FSMContext, storage: Storage) -> None:
    waterproofing = call.data.endswith("1")
    await call.answer()
    data = await state.get_data()

    if data.get("mode") == "room":
        surfaces = room_surfaces(
            data["walls"], data["height_m"], with_floor=data.get("with_floor", False)
        )
    else:
        surfaces = [
            Surface(
                name=("Стена" if data["kind"] == "wall" else "Пол")
                + f" {data.get('surface_no', 0) + 1}",
                width_mm=data["width_mm"],
                height_mm=data["height_mm"],
                kind=SurfaceKind(data["kind"]),
            )
        ]

    tile = Tile(
        width_mm=data["tile_w"],
        height_mm=data["tile_h"],
        thickness_mm=data["thickness_mm"],
        joint_mm=data["joint_mm"],
        per_pack=data.get("per_pack"),
        price_per_m2=data.get("price_per_m2"),
    )
    pattern = LayoutPattern(data["pattern"])
    waste = data.get("waste")

    # На пол мастер мог взять свою плитку — крупнее и своей пачкой.
    floor_tile = tile
    if data.get("floor_w"):
        floor_tile = Tile(
            width_mm=data["floor_w"],
            height_mm=data["floor_h"],
            thickness_mm=data["thickness_mm"],
            joint_mm=data["joint_mm"],
            per_pack=data.get("floor_per_pack"),
        )

    # «Реши сам» — это перебор стартов при раскладке; ориентацию стен выбираем
    # от угла, как и раньше.
    raw_start = data["start_from"]
    resolve_start = raw_start == "auto"
    start_from = StartFrom.EDGE if resolve_start else StartFrom(raw_start)

    saved_all = [
        SavedSurface(
            surface=surface,
            # На пол мастер мог взять свою плитку — крупнее и своей пачкой.
            tile=tile if surface.kind is SurfaceKind.WALL else floor_tile,
            pattern=pattern,
            start_from=start_from,
            waterproofing=waterproofing,
            waste=waste,
        )
        for surface in surfaces
    ]
    result = compute_project(saved_all, resolve_start=resolve_start)

    for layout in result.layouts:
        saved = await storage.add_surface(
            data["project_id"],
            call.from_user.id,
            surface_to_payload(
                layout.surface,
                layout.tile,
                layout.pattern,
                layout.start_from,
                waterproofing=waterproofing,
                waste=waste,
            ),
        )
        if not saved:
            await state.clear()
            await call.message.answer("Объект не найден.", reply_markup=kb.MAIN_MENU)
            return

    await state.update_data(surface_no=data.get("surface_no", 0) + len(surfaces))
    await state.set_state(None)
    await _show_result(call.message, data, result)


async def _tile_texture(bot: Bot, file_id: str | None) -> PilImage | None:
    """Фото плитки из Telegram — картинкой для схемы.

    Если фото не отдалось (удалили, битый файл), схема рисуется как раньше:
    показать серые квадратики лучше, чем не показать ничего.
    """
    if not file_id:
        return None
    try:
        buf = io.BytesIO()
        await bot.download(file_id, destination=buf)
        buf.seek(0)
        return Image.open(buf).convert("RGB")
    except Exception:
        logger.exception("не смог скачать фото плитки %s", file_id)
        return None


async def _show_result(
    message: Message,
    data: dict,
    result: ProjectResult,
    *,
    tile_photo: PilImage | None = None,
) -> None:
    """Схемы всех поверхностей плюс один список закупки на них."""
    title = data.get("title", "")
    project_id = data["project_id"]
    markup = kb.after_surface(project_id, wrap=result.head.wrap, can_wrap=result.can_wrap)

    def draw(lay: Layout) -> bytes:
        return render_layout(
            lay,
            title=f"{lay.surface.name} — {title}".strip(" —"),
            tile_photo=tile_photo,
            grout=result.head.grout,
        )

    layouts = result.layouts
    if len(layouts) == 1:
        await message.answer_photo(
            BufferedInputFile(draw(layouts[0]), filename="scheme.png"),
            caption=_caption(result),
            reply_markup=markup,
        )
        return

    # Комната: схемы альбомом, чтобы не сыпать сообщениями, а закупка — одна.
    media = [
        InputMediaPhoto(media=BufferedInputFile(draw(lay), filename=f"scheme_{i}.png"))
        for i, lay in enumerate(layouts, start=1)
    ]
    for chunk in (media[i : i + 10] for i in range(0, len(media), 10)):
        await message.answer_media_group(chunk)

    await message.answer(_caption(result), reply_markup=markup)


def _caption(result: ProjectResult) -> str:
    """Сводка по посчитанным поверхностям: площадь, плитка, закупка одним списком."""
    tile = result.tile
    area = result.area_m2

    if len(result.layouts) == 1:
        head = f"<b>{result.layouts[0].surface.name}</b> — {area:.2f} м²"
    else:
        floor = " + пол" if result.has_floor else ""
        counted = plural(len(result.walls), "стена", "стены", "стен")
        mode = " · эконом по кругу" if result.head.wrap else ""
        head = f"<b>Комната целиком</b> — {counted}{floor}, {area:.2f} м²{mode}"

    # Как плитка легла — не то же самое, что мастер ввёл: ориентацию бот подбирает
    # сам. Показываем прямо и подсказываем, что это его решение, а не приговор.
    lying = "лёжа" if tile.width_mm >= tile.height_mm else "стоя"
    lines = [
        head,
        f"Плитка {tile.width_mm:.0f}×{tile.height_mm:.0f} ({lying}), "
        f"шов {fmt_mm(tile.joint_mm)} мм",
        f"Класть: <b>{result.tiles_grid} шт</b> (резаных {result.cuts_count})",
        "",
        "<b>Купить:</b>",
    ]
    for line in result.purchase:
        note = f" <i>({line.note})</i>" if line.note else ""
        lines.append(f"• {line.name}: <b>{line.format_qty()} {line.unit}</b>{note}")

    if (cost := result.tile_cost) is not None:
        lines.append(f"\nПлитка на {money(cost)}")

    if saved := _fmt_savings(result.savings):
        lines.append(f"\n💰 Эконом сберёг <b>{saved}</b>: остатки уходят за угол, а не в мусор.")

    if advice := result.advice:
        lines.append("")
        lines += [f"💡 {a}" for a in advice]

    return "\n".join(lines)


def _fmt_savings(savings: Savings | None) -> str:
    """«Сколько я не купил» — в плитках и упаковках, а не в процентах."""
    if savings is None:
        return ""
    out = f"{savings.tiles} {plural(savings.tiles, 'плитку', 'плитки', 'плиток')}"
    if savings.packs > 0:
        out += (
            f" — это {savings.packs} "
            f"{plural(savings.packs, 'упаковка', 'упаковки', 'упаковок')}"
        )
    return out


# --- Смена раскладки и проёмы ------------------------------------------------


@router.callback_query(F.data.startswith("repat:"))
async def ask_repattern(call: CallbackQuery, storage: Storage) -> None:
    project_id = int(call.data.split(":")[1])
    project = await storage.get_project(project_id, call.from_user.id)
    if project is None or not project.surfaces:
        await call.answer("Объект не найден.", show_alert=True)
        return

    current = payload_to_surface(project.surfaces[0].dump()).pattern
    await call.answer()
    await call.message.answer(
        "Переложить объект другой раскладкой — посмотреть, как выйдет:",
        reply_markup=kb.repattern(project_id, current),
    )


@router.callback_query(F.data.startswith("setpat:"))
async def do_repattern(call: CallbackQuery, storage: Storage) -> None:
    _, raw_id, raw_pattern = call.data.split(":")
    project_id = int(raw_id)

    if not await storage.set_project_pattern(project_id, call.from_user.id, raw_pattern):
        await call.answer("Объект не найден.", show_alert=True)
        return

    await call.answer("Пересчитал")
    await _redraw(call.message, call.from_user.id, storage, project_id)


@router.callback_query(F.data.startswith("wrap:"))
async def set_wrap(call: CallbackQuery, storage: Storage) -> None:
    """Эконом-раскладка: стены одной лентой по кругу вместо стены-по-отдельности.

    Просьба Сани (16.07): обычная раскладка бьёт целую плитку об угол и
    выбрасывает остаток на каждой стене — «огромный расход». Лента пускает
    остаток за угол на следующую стену.
    """
    _, raw_id, raw_on = call.data.split(":")
    project_id = int(raw_id)
    on = raw_on == "1"

    project = await storage.get_project(project_id, call.from_user.id)
    if project is None or not project.surfaces:
        await call.answer("Объект не найден.", show_alert=True)
        return

    saved_all = [payload_to_surface(row.dump()) for row in project.surfaces]
    if on and not supports_wrap(saved_all[0].pattern):
        await call.answer(
            "Под 45° так не выйдет: там и так режется весь периметр. "
            "Эконом работает на «шов в шов» и «вразбежку».",
            show_alert=True,
        )
        return

    if not await storage.update_project_surfaces(project_id, call.from_user.id, wrap=on):
        await call.answer("Объект не найден.", show_alert=True)
        return

    await call.answer("Пересчитал по кругу" if on else "Вернул обычную")
    await _redraw(call.message, call.from_user.id, storage, project_id)


async def _redraw(message: Message, user_id: int, storage: Storage, project_id: int) -> None:
    """Пересчитать объект из сохранённых замеров и показать заново.

    Сюда сходятся все «а покажи иначе»: другая раскладка, фото плитки, цвет
    затирки. Замеры мастер вводил один раз — второй раз спрашивать их незачем.
    """
    project = await storage.get_project(project_id, user_id)
    if project is None or not project.surfaces:
        await message.answer("Объект не найден.", reply_markup=kb.MAIN_MENU)
        return

    result = compute_project([payload_to_surface(row.dump()) for row in project.surfaces])
    await _show_result(
        message,
        {"project_id": project_id, "title": project.title},
        result,
        tile_photo=await _tile_texture(message.bot, result.head.tile_photo_id),
    )


# --- Фото плитки и цвет затирки ----------------------------------------------


@router.callback_query(F.data.startswith("resize:"))
async def ask_resize(call: CallbackQuery, state: FSMContext, storage: Storage) -> None:
    """Сменить размер плитки — «а если взять другую?» — без пересоздания объекта."""
    project_id = int(call.data.split(":")[1])
    project = await storage.get_project(project_id, call.from_user.id)
    if project is None or not project.surfaces:
        await call.answer("Объект не найден.", show_alert=True)
        return

    kinds = {payload_to_surface(r.dump()).surface.kind for r in project.surfaces}
    await call.answer()

    # Спрашиваем «стены или пол», только если есть и то, и другое: у пола своя плитка.
    if len(kinds) > 1:
        await call.message.answer("Где меняем плитку?", reply_markup=kb.tile_target(project_id))
        return

    only = next(iter(kinds))
    await _ask_new_size(call.message, state, project_id, only.value)


@router.callback_query(F.data.startswith("resizeat:"))
async def pick_resize_target(call: CallbackQuery, state: FSMContext) -> None:
    _, raw_id, kind = call.data.split(":")
    await call.answer()
    await _ask_new_size(call.message, state, int(raw_id), kind)


async def _ask_new_size(message: Message, state: FSMContext, project_id: int, kind: str) -> None:
    await state.update_data(project_id=project_id, resize_kind=kind)
    await state.set_state(Tiling.resize)
    where = "на стенах" if kind == SurfaceKind.WALL.value else "на полу"
    await message.answer(
        f"Новый размер плитки {where} — ширина и высота:\n\n<code>30 60</code>\n"
        "<i>Пересчитаю раскладку и закупку по всему объекту.</i>"
    )


@router.message(Tiling.resize)
async def got_new_size(message: Message, state: FSMContext, storage: Storage) -> None:
    try:
        values = numbers(message.text or "")
    except ParseError as e:
        await message.answer(f"{e}\n\nПример: <code>30 60</code>")
        return
    if len(values) != 2 or values[0] <= 0 or values[1] <= 0:
        await message.answer("Нужно два числа: <code>30 60</code>")
        return

    data = await state.get_data()
    project_id, kind = data.get("project_id"), data.get("resize_kind")
    if project_id is None or kind is None:
        await state.set_state(None)
        await message.answer("Не понял, какой объект. Открой его заново.")
        return

    ok = await storage.set_tile_size(
        project_id,
        message.from_user.id,
        _tile_mm(values[0]),
        _tile_mm(values[1]),
        kind=kind,
    )
    if not ok:
        await state.set_state(None)
        await message.answer("Объект не найден.", reply_markup=kb.MAIN_MENU)
        return

    await state.set_state(None)
    await _redraw(message, message.from_user.id, storage, project_id)


@router.callback_query(F.data.startswith("restart:"))
async def ask_restart(call: CallbackQuery, storage: Storage) -> None:
    project_id = int(call.data.split(":")[1])
    project = await storage.get_project(project_id, call.from_user.id)
    if project is None or not project.surfaces:
        await call.answer("Объект не найден.", show_alert=True)
        return

    current = payload_to_surface(project.surfaces[0].dump()).start_from
    await call.answer()
    await call.message.answer(
        "Откуда ведём ряд?\n\n"
        "<i>От угла — целая плитка в углу, вся подрезка уходит в другой край. "
        "От центра — подрезка делится поровну на два края, смотрится аккуратнее.</i>",
        reply_markup=kb.restart_from(project_id, current),
    )


@router.callback_query(F.data.startswith("setstart:"))
async def set_start(call: CallbackQuery, storage: Storage) -> None:
    _, raw_id, start = call.data.split(":")
    project_id = int(raw_id)

    # «Реши сам» перебирает старты при каждом пересчёте, поэтому в базе держим
    # обычный старт — иначе кнопка-галочка показывала бы не то, что легло.
    stored = StartFrom.EDGE.value if start == "auto" else start
    if not await storage.update_project_surfaces(project_id, call.from_user.id, start_from=stored):
        await call.answer("Объект не найден.", show_alert=True)
        return

    await call.answer("Пересчитал")
    await _redraw(call.message, call.from_user.id, storage, project_id)


@router.callback_query(F.data.startswith("schemes:"))
async def show_schemes(call: CallbackQuery, storage: Storage) -> None:
    """Схемы раскладки по объекту — со всем, что мастер уже настроил."""
    project_id = int(call.data.split(":")[1])
    await call.answer()
    await _redraw(call.message, call.from_user.id, storage, project_id)


@router.callback_query(F.data.startswith("rotate:"))
async def rotate_tile(call: CallbackQuery, storage: Storage) -> None:
    """Положить плитку на бок: 70×20 → 20×70.

    До этого ориентацию выбирал бот — по самой широкой подрезке. Но как плитка
    лежит, решает мастер: там рисунок и вкус заказчика, а не только подрезка.
    """
    project_id = int(call.data.split(":")[1])
    if not await storage.rotate_tile(project_id, call.from_user.id):
        await call.answer("Объект не найден.", show_alert=True)
        return

    await call.answer("Повернул")
    await _redraw(call.message, call.from_user.id, storage, project_id)


@router.callback_query(F.data.startswith("tilephoto:"))
async def ask_tile_photo(call: CallbackQuery, state: FSMContext) -> None:
    project_id = int(call.data.split(":")[1])
    await state.update_data(project_id=project_id)
    await state.set_state(Tiling.tile_photo)
    await call.answer()
    await call.message.answer(
        "Пришли <b>фото плитки</b> — и на схеме будет она, а не белые квадраты.\n\n"
        "<i>Сфоткай саму плитку прямо в магазине или пачку дома. Лучше одну плитку "
        "целиком, ровно, без бликов — так рисунок ляжет точнее.</i>"
    )


@router.message(Tiling.tile_photo, F.photo)
async def got_tile_photo(message: Message, state: FSMContext, storage: Storage) -> None:
    data = await state.get_data()
    project_id = data.get("project_id")
    if project_id is None:
        await state.set_state(None)
        await message.answer("Не понял, к какому объекту. Открой его заново.")
        return

    # Берём самый крупный размер — Telegram отдаёт лесенку превью.
    file_id = message.photo[-1].file_id
    if not await storage.update_project_surfaces(
        project_id, message.from_user.id, tile_photo_id=file_id
    ):
        await state.set_state(None)
        await message.answer("Объект не найден.", reply_markup=kb.MAIN_MENU)
        return

    await state.set_state(None)
    await message.answer("Взял твою плитку. Перерисовываю…")
    await _redraw(message, message.from_user.id, storage, project_id)


@router.message(Tiling.tile_photo, ~F.photo)
async def not_a_tile_photo(message: Message) -> None:
    await message.answer("Жду фото плитки. Или жми любую кнопку меню.")


@router.message(Tiling.price)
async def got_tile_price(message: Message, state: FSMContext, storage: Storage) -> None:
    """Фактическая цена плитки — для акта, когда мастер закупался сам."""
    try:
        price = single_number(message.text or "", minimum=0)
    except ParseError as e:
        await message.answer(f"{e}\n\nПример: <code>1450</code>")
        return

    data = await state.get_data()
    project_id = data.get("project_id")
    if project_id is None:
        await state.set_state(None)
        await message.answer("Не понял, к какому объекту. Открой его заново.")
        return

    if not await storage.set_tile_price(project_id, message.from_user.id, price or None):
        await state.set_state(None)
        await message.answer("Объект не найден.", reply_markup=kb.MAIN_MENU)
        return

    await state.set_state(None)
    await message.answer(f"Записал: плитка по {money(price)} за м².")

    # Импорт по месту: projects импортирует состояния отсюда — иначе круг.
    from tilebot.bot.handlers.projects import show_act

    await show_act(message, message.from_user.id, storage, project_id)


@router.callback_query(F.data.startswith("offset:"))
async def ask_offset(call: CallbackQuery, storage: Storage) -> None:
    """Смещение рядов вразбежку: половина плитки или треть (палубная)."""
    project_id = int(call.data.split(":")[1])
    project = await storage.get_project(project_id, call.from_user.id)
    if project is None or not project.surfaces:
        await call.answer("Объект не найден.", show_alert=True)
        return

    head = payload_to_surface(project.surfaces[0].dump())
    if head.pattern is not LayoutPattern.BRICK:
        await call.answer("Смещение есть только у раскладки «вразбежку».", show_alert=True)
        return

    await call.answer()
    await call.message.answer(
        "На сколько сдвигать каждый ряд?\n\n"
        "<i>1/2 — классический кирпич. 1/3 — палубная: так кладут длинную плитку, "
        "иначе край гуляет и рисунок идёт лесенкой.</i>",
        reply_markup=kb.brick_offsets(project_id, head.offset_ratio),
    )


@router.callback_query(F.data.startswith("setoffset:"))
async def set_offset(call: CallbackQuery, storage: Storage) -> None:
    _, raw_id, label = call.data.split(":")
    project_id = int(raw_id)
    ratio = BRICK_OFFSETS.get(label, DEFAULT_OFFSET)

    if not await storage.update_project_surfaces(
        project_id, call.from_user.id, offset_ratio=ratio
    ):
        await call.answer("Объект не найден.", show_alert=True)
        return

    await call.answer("Пересчитал")
    await _redraw(call.message, call.from_user.id, storage, project_id)


@router.callback_query(F.data.startswith("groutkind:"))
async def ask_grout_kind(call: CallbackQuery, storage: Storage) -> None:
    project_id = int(call.data.split(":")[1])
    project = await storage.get_project(project_id, call.from_user.id)
    if project is None or not project.surfaces:
        await call.answer("Объект не найден.", show_alert=True)
        return

    current = payload_to_surface(project.surfaces[0].dump()).grout_kind
    await call.answer()
    await call.message.answer(
        "Чем затираем?\n\n"
        "<i>Эпоксидная не боится воды и не темнеет, но затирать её дольше и муторнее — "
        "это дороже в работе и сама она в разы дороже. Цементная — обычный вариант.</i>",
        reply_markup=kb.grout_kinds(project_id, current),
    )


@router.callback_query(F.data.startswith("setgroutkind:"))
async def set_grout_kind(call: CallbackQuery, storage: Storage) -> None:
    _, raw_id, kind = call.data.split(":")
    project_id = int(raw_id)

    if not await storage.update_project_surfaces(project_id, call.from_user.id, grout_kind=kind):
        await call.answer("Объект не найден.", show_alert=True)
        return

    await call.answer("Пересчитал")
    await _redraw(call.message, call.from_user.id, storage, project_id)


@router.callback_query(F.data.startswith("grout:"))
async def ask_grout(call: CallbackQuery, storage: Storage) -> None:
    project_id = int(call.data.split(":")[1])
    project = await storage.get_project(project_id, call.from_user.id)
    if project is None or not project.surfaces:
        await call.answer("Объект не найден.", show_alert=True)
        return

    current = payload_to_surface(project.surfaces[0].dump()).grout
    await call.answer()
    await call.message.answer(
        "Какая затирка?\n\n<i>Тёмная на светлой плитке подчёркивает шов, "
        "светлая прячет. На схеме сразу видно, как выйдет.</i>",
        reply_markup=kb.grout_colors(project_id, current),
    )


@router.callback_query(F.data.startswith("setgrout:"))
async def set_grout(call: CallbackQuery, storage: Storage) -> None:
    _, raw_id, color = call.data.split(":")
    project_id = int(raw_id)

    if not await storage.update_project_surfaces(project_id, call.from_user.id, grout=color):
        await call.answer("Объект не найден.", show_alert=True)
        return

    await call.answer("Перерисовываю")
    await _redraw(call.message, call.from_user.id, storage, project_id)


@router.callback_query(F.data.startswith("opening:"))
async def ask_opening(call: CallbackQuery, state: FSMContext, storage: Storage) -> None:
    project_id = int(call.data.split(":")[1])
    project = await storage.get_project(project_id, call.from_user.id)
    if project is None or not project.surfaces:
        await call.answer("Объект не найден.", show_alert=True)
        return

    await call.answer()
    if len(project.surfaces) == 1:
        await _ask_opening_size(call.message, project.surfaces[0].id, state=state)
        return

    await call.message.answer(
        "В какой стене проём?",
        reply_markup=kb.surfaces_list(project_id, project.surfaces, "openat"),
    )


@router.callback_query(F.data.startswith("openat:"))
async def pick_opening_surface(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await _ask_opening_size(call.message, int(call.data.split(":")[1]), state=state)


async def _ask_opening_size(message: Message, surface_id: int, *, state: FSMContext) -> None:
    await state.update_data(surface_id=surface_id)
    await state.set_state(Tiling.opening_size)
    await message.answer(
        "Размер проёма — <b>ширина и высота</b>:\n\n"
        "<code>дверь 0.8 2.1</code>\n"
        "Несколько — с новой строки. Знаешь, где именно, — добавь отступ слева и снизу: "
        "<code>дверь 0.8 2.1 от 1.9 0</code>\n\n"
        "<i>С координатами не посчитаю плитку, уходящую в проём, — выйдет точнее.</i>",
    )


@router.message(Tiling.opening_size)
async def got_opening(message: Message, state: FSMContext, storage: Storage) -> None:
    data = await state.get_data()
    surface_id = data.get("surface_id")
    if surface_id is None:
        await state.set_state(None)
        await message.answer("Не понял, к какой стене проём. Открой объект заново.")
        return

    try:
        openings = _parse_openings(message.text or "")
    except ParseError as e:
        await message.answer(f"{e}\n\nПример: <code>дверь 0.8 2.1</code>")
        return

    row = await storage.get_surface(surface_id, message.from_user.id)
    if row is None:
        await state.set_state(None)
        await message.answer("Поверхность не найдена.", reply_markup=kb.MAIN_MENU)
        return

    saved = payload_to_surface(row.dump())
    with_opening = replace(
        saved, surface=replace(saved.surface, openings=[*saved.surface.openings, *openings])
    )
    result = compute_project([with_opening])
    layout = result.layouts[0]
    surface = layout.surface

    await storage.update_surface(
        surface_id,
        message.from_user.id,
        surface_to_payload(
            layout.surface,
            layout.tile,
            layout.pattern,
            layout.start_from,
            waterproofing=saved.waterproofing,
            waste=saved.waste,
            # Проём — не повод забыть фото плитки, затирку и поворот: пересохраняем
            # поверхность целиком, а не половину.
            tile_photo_id=saved.tile_photo_id,
            grout=saved.grout,
            tile_locked=saved.tile_locked,
        ),
    )
    await state.set_state(None)

    project_id = row.project_id
    png = render_layout(layout, title=surface.name)
    await message.answer_photo(
        BufferedInputFile(png, filename="scheme.png"),
        caption=_caption(result),
        reply_markup=kb.after_surface(project_id),
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


@router.message(StateFilter(None), F.text.regexp(r"^\d"))
async def stray_numbers(message: Message) -> None:
    """Мастер прислал числа, не начав расчёт — подскажем, куда нажать."""
    await message.answer(
        "Чтобы посчитать, нажми <b>🧱 Плитка</b> или <b>📐 Площадь</b>.",
        reply_markup=kb.MAIN_MENU,
    )
