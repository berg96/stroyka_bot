from aiogram.fsm.state import StatesGroup, State

class AreaState(StatesGroup):
    waiting_for_sides = State()
