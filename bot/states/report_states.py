from aiogram.fsm.state import State, StatesGroup


class ReportUploadState(StatesGroup):
    waiting_for_file = State()
