"""Клавиатуры. Кнопки крупные и понятные — мастер тыкает их мокрым пальцем на объекте."""

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from tilebot.core.models import GroutKind, LayoutPattern, StartFrom
from tilebot.render.scheme import GROUT_COLORS

MAIN_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🧱 Плитка"), KeyboardButton(text="📐 Площадь")],
        [KeyboardButton(text="📋 Мои объекты"), KeyboardButton(text="💵 Долги")],
        [KeyboardButton(text="💰 Прайс")],
    ],
    resize_keyboard=True,
    input_field_placeholder="Выбери, что считаем",
)

AREA_SHAPES = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="▭ Прямоугольник", callback_data="shape:rect")],
        [InlineKeyboardButton(text="◺ Треугольник (3 стороны)", callback_data="shape:tri")],
        [InlineKeyboardButton(text="◇ Четырёхугольник (+ диагональ)", callback_data="shape:quad")],
        [InlineKeyboardButton(text="⬠ Многоугольник", callback_data="shape:poly")],
        [InlineKeyboardButton(text="⌐ Г-образная / с коробом", callback_data="shape:composite")],
    ]
)

TILING_MODE = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="🛁 Комната целиком", callback_data="mode:room")],
        [InlineKeyboardButton(text="▭ Одна стена или пол", callback_data="mode:single")],
    ]
)

# Ходовые швы. «Полтора» — то, что мастер кладёт по умолчанию; 1 мм почти не
# встречается, поэтому в кнопках его нет — только через «свой».
JOINTS = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="1,5 мм", callback_data="joint:1.5"),
            InlineKeyboardButton(text="2 мм", callback_data="joint:2"),
            InlineKeyboardButton(text="3 мм", callback_data="joint:3"),
        ],
        [InlineKeyboardButton(text="Свой размер", callback_data="joint:custom")],
    ]
)

THICKNESS = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="8 мм", callback_data="thick:8"),
            InlineKeyboardButton(text="9 мм", callback_data="thick:9"),
            InlineKeyboardButton(text="10 мм", callback_data="thick:10"),
        ],
        [InlineKeyboardButton(text="Не знаю — считай 9", callback_data="thick:9")],
    ]
)


def waste_options(suggested: int) -> InlineKeyboardMarkup:
    """Запас плитки. Подсказанный вариант помечаем — он же и норма под раскладку."""
    b = InlineKeyboardBuilder()
    for percent in (7, 10, 15):
        mark = " ✓" if percent == suggested else ""
        b.button(text=f"{percent}%{mark}", callback_data=f"waste:{percent}")
    b.adjust(3)
    return b.as_markup()


ROOM_FLOOR = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="Да, и пол", callback_data="floor:1"),
            InlineKeyboardButton(text="Только стены", callback_data="floor:0"),
        ]
    ]
)

QUAD_ANGLES = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="📐 Углы прямые", callback_data="quad:right")],
        [InlineKeyboardButton(text="◇ Есть косой угол", callback_data="quad:skew")],
    ]
)

SURFACE_KIND = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="Стена", callback_data="kind:wall"),
            InlineKeyboardButton(text="Пол", callback_data="kind:floor"),
        ]
    ]
)

PATTERNS = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="Шов в шов", callback_data=f"pat:{LayoutPattern.STRAIGHT}"),
            InlineKeyboardButton(text="Вразбежку", callback_data=f"pat:{LayoutPattern.BRICK}"),
        ],
        [
            InlineKeyboardButton(text="Диагональ", callback_data=f"pat:{LayoutPattern.DIAGONAL}"),
            InlineKeyboardButton(text="Ёлочка", callback_data=f"pat:{LayoutPattern.HERRINGBONE}"),
        ],
    ]
)

START_FROM = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="От угла", callback_data=f"start:{StartFrom.EDGE}"),
            InlineKeyboardButton(text="От центра", callback_data=f"start:{StartFrom.CENTER}"),
        ],
        [InlineKeyboardButton(text="Как лучше — реши сам", callback_data="start:auto")],
    ]
)

YES_NO_WATERPROOF = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="Да, мокрая зона", callback_data="wp:1"),
            InlineKeyboardButton(text="Не нужна", callback_data="wp:0"),
        ]
    ]
)

SKIP = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="Пропустить", callback_data="skip")]]
)

SAME_TILE = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="Такая же, как на стены", callback_data="same_tile")]
    ]
)


def after_surface(project_id: int) -> InlineKeyboardMarkup:
    """Что делать, когда поверхность посчитана."""
    b = InlineKeyboardBuilder()
    b.button(text="🔀 Сменить раскладку", callback_data=f"repat:{project_id}")
    b.button(text="↔️ Начало ряда", callback_data=f"restart:{project_id}")
    b.button(text="🔄 Повернуть плитку", callback_data=f"rotate:{project_id}")
    b.button(text="📏 Размер плитки", callback_data=f"resize:{project_id}")
    b.button(text="🖼 Фото плитки", callback_data=f"tilephoto:{project_id}")
    b.button(text="🎨 Цвет затирки", callback_data=f"grout:{project_id}")
    b.button(text="🧴 Вид затирки", callback_data=f"groutkind:{project_id}")
    b.button(text="🚪 Учесть проём", callback_data=f"opening:{project_id}")
    b.button(text="➕ Ещё стена / пол", callback_data=f"add_surface:{project_id}")
    b.button(text="🧾 Итог по объекту", callback_data=f"summary:{project_id}")
    b.button(text="💵 Смета заказчику", callback_data=f"estimate:{project_id}")
    # Смета — до работ и по прайсу. Акт — после: по факту, с материалами, если
    # мастер закупался сам.
    b.button(text="📄 Акт выполненных работ", callback_data=f"act:{project_id}")
    b.adjust(2, 2, 1)
    return b.as_markup()


def grout_kinds(project_id: int, current: GroutKind) -> InlineKeyboardMarkup:
    """Цементная или эпоксидная: разный расход и разная цена работы."""
    b = InlineKeyboardBuilder()
    for kind, title in ((GroutKind.CEMENT, "Цементная"), (GroutKind.EPOXY, "Эпоксидная")):
        mark = " ✓" if kind is current else ""
        b.button(text=f"{title}{mark}", callback_data=f"setgroutkind:{project_id}:{kind.value}")
    b.button(text="⬅️ Назад", callback_data=f"open:{project_id}")
    b.adjust(2, 1)
    return b.as_markup()


def tile_target(project_id: int) -> InlineKeyboardMarkup:
    """Где менять плитку: на стенах или на полу — они бывают разные."""
    b = InlineKeyboardBuilder()
    b.button(text="Стены", callback_data=f"resizeat:{project_id}:wall")
    b.button(text="Пол", callback_data=f"resizeat:{project_id}:floor")
    b.button(text="⬅️ Назад", callback_data=f"open:{project_id}")
    b.adjust(2, 1)
    return b.as_markup()


def grout_colors(project_id: int, current: str | None) -> InlineKeyboardMarkup:
    """Затирка: мастер выбирает мешок в магазине, а не hex."""
    b = InlineKeyboardBuilder()
    for key, (title, _rgb) in GROUT_COLORS.items():
        mark = " ✓" if key == current else ""
        b.button(text=f"{title}{mark}", callback_data=f"setgrout:{project_id}:{key}")
    b.button(text="⬅️ Назад", callback_data=f"open:{project_id}")
    b.adjust(2, 2, 1, 1)
    return b.as_markup()


def restart_from(project_id: int, current: StartFrom | None) -> InlineKeyboardMarkup:
    """Откуда вести ряд. Меняется после расчёта — посмотреть, где ляжет подрезка."""
    b = InlineKeyboardBuilder()
    for value, title in (
        (StartFrom.EDGE.value, "От угла"),
        (StartFrom.CENTER.value, "От центра"),
        ("auto", "Реши сам"),
    ):
        mark = " ✓" if current is not None and value == current.value else ""
        b.button(text=f"{title}{mark}", callback_data=f"setstart:{project_id}:{value}")
    b.button(text="⬅️ Назад", callback_data=f"open:{project_id}")
    b.adjust(2, 1, 1)
    return b.as_markup()


def repattern(project_id: int, current: LayoutPattern) -> InlineKeyboardMarkup:
    """Переложить объект другой раскладкой — посмотреть и так, и так."""
    b = InlineKeyboardBuilder()
    titles = {
        LayoutPattern.STRAIGHT: "Шов в шов",
        LayoutPattern.BRICK: "Вразбежку",
        LayoutPattern.DIAGONAL: "Диагональ",
        LayoutPattern.HERRINGBONE: "Ёлочка",
    }
    for pattern, title in titles.items():
        mark = " ✓" if pattern is current else ""
        b.button(text=f"{title}{mark}", callback_data=f"setpat:{project_id}:{pattern.value}")
    b.button(text="⬅️ Назад", callback_data=f"open:{project_id}")
    b.adjust(2, 2, 1)
    return b.as_markup()


def surfaces_list(project_id: int, surfaces: list, action: str) -> InlineKeyboardMarkup:
    """Выбор поверхности объекта — например, к какой стене относится проём."""
    b = InlineKeyboardBuilder()
    for row in surfaces:
        b.button(text=row.dump()["surface"]["name"], callback_data=f"{action}:{row.id}")
    b.button(text="⬅️ Назад", callback_data=f"open:{project_id}")
    b.adjust(1)
    return b.as_markup()


def project_actions(project_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    # Схемы шлются сразу после расчёта, но объект живёт дальше: вернулся к нему
    # завтра — и посмотреть раскладку было негде.
    b.button(text="📐 Схемы раскладки", callback_data=f"schemes:{project_id}")
    b.button(text="🧾 Итог по объекту", callback_data=f"summary:{project_id}")
    b.button(text="💵 Смета заказчику", callback_data=f"estimate:{project_id}")
    b.button(text="💰 Деньги", callback_data=f"money:{project_id}")
    b.button(text="📷 Фото", callback_data=f"photos:{project_id}")
    b.button(text="➕ Добавить поверхность", callback_data=f"add_surface:{project_id}")
    b.button(text="🗑 Удалить объект", callback_data=f"delete:{project_id}")
    b.adjust(1)
    return b.as_markup()


def money_actions(project_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="➕ Записать платёж", callback_data=f"addpay:{project_id}")
    b.button(text="✏️ Сумма договора", callback_data=f"setdeal:{project_id}")
    b.button(text="📷 Фото объекта", callback_data=f"addphoto:{project_id}")
    b.button(text="⬅️ К объекту", callback_data=f"open:{project_id}")
    b.adjust(1)
    return b.as_markup()


def projects_list(projects: list) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for p in projects:
        b.button(text=f"{p.title} ({len(p.surfaces)})", callback_data=f"open:{p.id}")
    b.adjust(1)
    return b.as_markup()


def price_fields() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for field, label in (
        ("wall_tiling", "Плитка на стену, ₽/м²"),
        ("floor_tiling", "Плитка на пол, ₽/м²"),
        ("waterproofing", "Гидроизоляция, ₽/м²"),
        ("priming", "Грунтовка, ₽/м²"),
        ("grouting", "Затирка цементной, ₽/м²"),
        ("grouting_epoxy", "Затирка эпоксидной, ₽/м²"),
        ("cutting", "Подрезка, ₽/шт"),
        ("demolition", "Демонтаж, ₽/м²"),
        ("min_order", "Минимальный заказ, ₽"),
        # Справочные цены материалов — правятся так же, как расценки на работу.
        ("mat_tile_m2", "🧱 Плитка, ₽/м²"),
        ("mat_glue_kg", "🧱 Клей, ₽/кг"),
        ("mat_grout_kg", "🧱 Затирка цем., ₽/кг"),
        ("mat_grout_epoxy_kg", "🧱 Затирка эпокс., ₽/кг"),
        ("mat_primer_l", "🧱 Грунтовка, ₽/л"),
        ("mat_waterproof_kg", "🧱 Гидроизоляция, ₽/кг"),
        ("mat_clip_pcs", "🧱 СВП-зажим, ₽/шт"),
        ("mat_cross_pcs", "🧱 Крестик, ₽/шт"),
        ("mat_tape_m", "🧱 Гидролента, ₽/м"),
    ):
        b.button(text=label, callback_data=f"price:{field}")
    b.adjust(1)
    return b.as_markup()
