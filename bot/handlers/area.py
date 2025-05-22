from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from bot.states.area import AreaState


router = Router()


@router.message(F.text == "Рассчитать площадь")
async def ask_sides(message: Message, state: FSMContext):
    await message.answer("Введите длины сторон (каждая с новой строки):")
    await state.set_state(AreaState.waiting_for_sides)

@router.message(AreaState.waiting_for_sides)
async def calculate_area(message: Message, state: FSMContext):
    sides = [float(x.replace(',', '.')) for x in message.text.strip().splitlines() if x.strip()]
    await state.clear()

    if len(sides) == 2:
        area = sides[0] * sides[1]
        await message.answer(f"Площадь прямоугольника: {area}")
    elif len(sides) == 3:
        a, b, c = sides
        p = (a + b + c) / 2
        area = (p * (p - a) * (p - b) * (p - c)) ** 0.5
        await message.answer(f"Площадь треугольника: {area:.2f}")
    else:
        await message.answer("Пока могу вычислить только площадь треугольника (3 стороны) или прямоугольника (2 стороны).")
