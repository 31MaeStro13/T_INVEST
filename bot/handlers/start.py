from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from bot.keyboards.reply_keyboards import get_main_menu_keyboard
from bot.lexicon.lexicon_ru import LEXICON_RU
from bot.services.api_client import BackendAPIClient

router = Router(name="start_router")


@router.message(CommandStart())
async def process_start_command(message: Message, api_client: BackendAPIClient):
    """Приветствие пользователя, проверка статуса токена и отправка меню."""
    user_status = await api_client.check_user_status(message.from_user.id)

    # Базовое приветствие с меню
    greeting = LEXICON_RU["start_greeting"]

    # Если токена еще нет в базе — мягко подсказываем привязать
    if not user_status or not user_status.get("has_token"):
        greeting += f"\n\n{LEXICON_RU['no_token_prompt']}"

    await message.answer(
        text=greeting,
        reply_markup=get_main_menu_keyboard(),
        parse_mode="HTML",
    )
