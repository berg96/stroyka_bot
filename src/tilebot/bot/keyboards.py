"""Клавиатуры. Кнопки крупные и понятные — мастер тыкает их мокрым пальцем на объекте."""

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from tilebot.core.models import LayoutPattern, StartFrom

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


def after_surface(project_id: int) -> InlineKeyboardMarkup:
    """Что делать, когда поверхность посчитана."""
    b = InlineKeyboardBuilder()
    b.button(text="➕ Ещё стена / пол", callback_data=f"add_surface:{project_id}")
    b.button(text="🧾 Итог по объекту", callback_data=f"summary:{project_id}")
    b.button(text="💵 Смета заказчику", callback_data=f"estimate:{project_id}")
    b.adjust(1)
    return b.as_markup()


def project_actions(project_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
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
        ("grouting", "Затирка швов, ₽/м²"),
        ("demolition", "Демонтаж, ₽/м²"),
        ("min_order", "Минимальный заказ, ₽"),
    ):
        b.button(text=label, callback_data=f"price:{field}")
    b.adjust(1)
    return b.as_markup()
