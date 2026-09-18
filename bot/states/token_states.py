from aiogram.fsm.state import State, StatesGroup


class TokenState(StatesGroup):
    waiting_for_token = State()
