from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
from bot.lexicon.lexicon_ru import LEXICON_RU


def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Главная клавиатура бота (Reply Keyboard)."""
    keyboard = [
        [
            KeyboardButton(text=LEXICON_RU["btn_portfolio"]),
            KeyboardButton(text=LEXICON_RU["btn_accounts"]),
        ],
        [
            KeyboardButton(text=LEXICON_RU["btn_sync"]),
            KeyboardButton(text=LEXICON_RU["btn_token"]),
        ],
    ]
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        persistent=True,
    )
