from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Рассчитать площадь")],
        [KeyboardButton(text="Рассчитать плитку")],
    ],
    resize_keyboard=True
)