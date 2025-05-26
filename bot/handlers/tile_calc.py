from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from states.tile_calc import TileCalcState
from utils.logger import log_user_action


router = Router()


@router.message(F.text == "Рассчитать плитку")
@log_user_action('Рассчитать плитку')
async def start_tile_calc(message: Message, state: FSMContext):
    await message.answer("Введите площадь помещения в м²:")
    await state.set_state(TileCalcState.waiting_for_area)

@router.message(TileCalcState.waiting_for_area)
async def get_room_area(message: Message, state: FSMContext):
    try:
        area = float(message.text)
        if area <= 0:
            raise ValueError()
        await state.update_data(room_area=area)
        await state.set_state(TileCalcState.waiting_for_tile_size)
        await message.answer("Введите размер плитки в СМ через пробел (например: 30 30):")
    except ValueError:
        await message.answer("Пожалуйста, введите положительное число.")

@router.message(TileCalcState.waiting_for_tile_size)
async def get_tile_size(message: Message, state: FSMContext):
    try:
        width, height = map(float, message.text.split())
        if width <= 0 or height <= 0:
            raise ValueError()
        await state.update_data(tile_width_cm=width, tile_height_cm=height)
        await state.set_state(TileCalcState.waiting_for_reserve_percent)
        await message.answer("Введите процент запаса (по умолчанию 10%):")
    except Exception:
        await message.answer("Введите два положительных числа через пробел (например: 30 30).")

@router.message(TileCalcState.waiting_for_reserve_percent)
async def get_reserve_and_calculate(message: Message, state: FSMContext):
    try:
        reserve = float(message.text)
        if reserve < 0:
            raise ValueError()
    except ValueError:
        reserve = 10.0  # по умолчанию

    data = await state.get_data()
    area = data["room_area"]
    tile_w, tile_h = data["tile_width_cm"], data["tile_height_cm"]
    tile_area = (tile_w / 100) * (tile_h / 100)  # в м²

    if tile_area == 0:
        await message.answer("Размер плитки не может быть нулевым.")
        return

    tiles_needed = (area / tile_area) * (1 + reserve / 100)
    tiles_needed_rounded = int(tiles_needed) + (1 if tiles_needed % 1 > 0 else 0)

    await message.answer(f"Вам потребуется примерно {tiles_needed_rounded} плиток с учётом {reserve}% запаса.")
    await state.clear()
