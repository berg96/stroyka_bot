"""Площадь помещения по замерам рулеткой.

То, с чего Саша начал год назад: «на Android было приложение — вводишь стороны, оно
считает площадь; на iPhone такого нет». Здесь оно есть, и честно объясняет, когда
одних сторон не хватает.
"""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from tilebot.bot import keyboards as kb
from tilebot.core.geometry import (
    AreaResult,
    GeometryError,
    Part,
    composite,
    polygon_fan,
    quadrilateral,
    rectangle,
    right_angled_quad,
    triangle,
)
from tilebot.core.parse import ParseError, meters, name_and_numbers
from tilebot.render.shape import render_parts, render_shape

router = Router(name="area")


class Area(StatesGroup):
    rect = State()
    tri = State()
    quad = State()
    quad_right = State()
    poly_sides = State()
    poly_diagonals = State()
    composite_parts = State()


@router.message(F.text == "📐 Площадь")
async def start_area(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "<b>Площадь помещения</b>\n\nКакая форма?",
        reply_markup=kb.AREA_SHAPES,
    )


@router.callback_query(F.data.startswith("shape:"))
async def pick_shape(call: CallbackQuery, state: FSMContext) -> None:
    shape = call.data.split(":", 1)[1]
    await call.answer()

    if shape == "rect":
        await state.set_state(Area.rect)
        await call.message.answer("Стороны через пробел:\n\n<code>4 3</code>")

    elif shape == "tri":
        await state.set_state(Area.tri)
        await call.message.answer("Три стороны через пробел:\n\n<code>3 4 5</code>")

    elif shape == "quad":
        await call.message.answer(
            "Углы в комнате прямые?\n\n"
            "<i>Если прямые — диагональ мерить не надо, посчитаю по сторонам. "
            "Диагональ нужна только там, где стена ушла вкось.</i>",
            reply_markup=kb.QUAD_ANGLES,
        )

    elif shape == "poly":
        await state.set_state(Area.poly_sides)
        await call.message.answer(
            "Стороны <b>по кругу</b>, через пробел:\n\n<code>4 3 2.8 2.8 3</code>\n\n"
            "<i>Потом попрошу диагонали из одного угла.</i>"
        )

    else:
        await state.set_state(Area.composite_parts)
        await state.update_data(parts=[])
        await call.message.answer(
            "Разбей комнату на <b>прямоугольные куски</b> — по одному в строке:\n\n"
            "<code>основная 4 3\nвыступ 2 2\nминус короб 0.4 0.6</code>\n\n"
            "<i>Кусок со словом «минус» вычитается. Так считается Г-образная комната "
            "или ванная с коробом — без всякой геометрии, одной рулеткой.</i>"
        )


def _reply(result: AreaResult, *, with_scheme: bool) -> str:
    lines = [f"<b>Площадь: {result.area_m2:.2f} м²</b>", f"<i>{result.method}</i>"]
    if result.perimeter_m:
        lines.append(f"Периметр: {result.perimeter_m:.2f} м")
    if result.note:
        lines.append(f"\n{result.note}")
    if with_scheme:
        lines.append("\n👆 Сверь фигуру со схемой: так ли стоят стены?")
    lines.append("\n💡 Плитку на эту площадь посчитаю в разделе <b>🧱 Плитка</b>.")
    return "\n".join(lines)


async def _answer(
    message: Message,
    state: FSMContext,
    result: AreaResult,
    parts: list[Part] | None = None,
) -> None:
    """Ответить площадью и схемой обмера — чтобы мастер увидел, ту ли фигуру посчитали."""
    await state.clear()

    png = render_parts(parts, result) if parts else render_shape(result)
    caption = _reply(result, with_scheme=png is not None)

    if png:
        await message.answer_photo(
            BufferedInputFile(png, filename="shape.png"),
            caption=caption,
            reply_markup=kb.MAIN_MENU,
        )
    else:
        await message.answer(caption, reply_markup=kb.MAIN_MENU)


@router.message(Area.rect)
async def calc_rect(message: Message, state: FSMContext) -> None:
    try:
        a, b = meters(message.text or "", count=2)
        await _answer(message, state, rectangle(a, b))
    except (ParseError, GeometryError) as e:
        await message.answer(f"{e}\n\nПример: <code>4 3</code>")


@router.message(Area.tri)
async def calc_tri(message: Message, state: FSMContext) -> None:
    try:
        a, b, c = meters(message.text or "", count=3)
        await _answer(message, state, triangle(a, b, c))
    except (ParseError, GeometryError) as e:
        await message.answer(f"{e}\n\nПример: <code>3 4 5</code>")


@router.callback_query(F.data.startswith("quad:"))
async def pick_quad_angles(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()

    if call.data.endswith("right"):
        await state.set_state(Area.quad_right)
        await call.message.answer(
            "Четыре стороны <b>по кругу</b>, через пробел:\n\n"
            "<code>2 1.8 2 1.8</code>\n\n"
            "<i>Диагональ не нужна — при прямых углах она считается сама.</i>"
        )
    else:
        await state.set_state(Area.quad)
        await call.message.answer(
            "Четыре стороны <b>по кругу</b> и <b>диагональ</b> — пять чисел:\n\n"
            "<code>4 3 4 3 5</code>\n\n"
            "<i>Тут диагональ обязательна: при косом угле одни стороны форму не "
            "задают — фигуру можно «перекосить», и площадь изменится. "
            "Меряй из угла в угол.</i>"
        )


@router.message(Area.quad_right)
async def calc_quad_right(message: Message, state: FSMContext) -> None:
    try:
        a, b, c, d = meters(message.text or "", count=4)
        await _answer(message, state, right_angled_quad(a, b, c, d))
    except (ParseError, GeometryError) as e:
        await message.answer(f"{e}\n\nПример: <code>2 1.8 2 1.8</code>")


@router.message(Area.quad)
async def calc_quad(message: Message, state: FSMContext) -> None:
    try:
        a, b, c, d, diag = meters(message.text or "", count=5)
        await _answer(message, state, quadrilateral(a, b, c, d, diag))
    except (ParseError, GeometryError) as e:
        await message.answer(f"{e}\n\nПример: <code>4 3 4 3 5</code>")


@router.message(Area.poly_sides)
async def calc_poly_sides(message: Message, state: FSMContext) -> None:
    try:
        sides = meters(message.text or "")
    except ParseError as e:
        await message.answer(str(e))
        return

    if len(sides) < 3:
        await message.answer("Нужно хотя бы три стороны.")
        return

    if len(sides) == 3:
        try:
            await _answer(message, state, triangle(*sides))
        except GeometryError as e:
            await message.answer(str(e))
        return

    need = len(sides) - 3
    await state.update_data(sides=sides)
    await state.set_state(Area.poly_diagonals)
    await message.answer(
        f"Теперь <b>{need}</b> диагонал{'ь' if need == 1 else 'и'} "
        f"из <b>первого угла</b> (откуда начинал мерить стороны) — через пробел.\n\n"
        "<i>Из этого угла тяни рулетку в каждый угол, кроме соседних. "
        "Комната режется на треугольники, а треугольник по трём сторонам считается точно.</i>"
    )


@router.message(Area.poly_diagonals)
async def calc_poly(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    try:
        diagonals = meters(message.text or "")
        await _answer(message, state, polygon_fan(data["sides"], diagonals))
    except (ParseError, GeometryError) as e:
        await message.answer(str(e))


@router.message(Area.composite_parts)
async def calc_composite(message: Message, state: FSMContext) -> None:
    parts: list[Part] = []
    try:
        for raw in (message.text or "").strip().splitlines():
            line = raw.strip()
            if not line:
                continue
            name, values = name_and_numbers(line)
            if len(values) != 2:
                raise ParseError(f"«{line}» — нужно два размера: <code>кухня 4 3</code>")
            parts.append(
                Part(
                    name=(name or "участок")[:24],
                    width_m=values[0],
                    length_m=values[1],
                    subtract=line.lower().lstrip("-− ").startswith("минус")
                    or raw.strip().startswith(("-", "−")),
                )
            )
        await _answer(message, state, composite(parts), parts=parts)
    except (ParseError, GeometryError) as e:
        await message.answer(f"{e}\n\nПример:\n<code>кухня 4 3\nминус короб 0.4 0.6</code>")
