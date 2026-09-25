from aiogram.fsm.state import State, StatesGroup


class AIAuditorState(StatesGroup):
    waiting_for_question = State()
