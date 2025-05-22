from aiogram.fsm.state import State, StatesGroup

class TileCalcState(StatesGroup):
    waiting_for_area = State()
    waiting_for_tile_size = State()
    waiting_for_reserve_percent = State()
