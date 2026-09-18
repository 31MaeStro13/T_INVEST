from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def get_cancel_token_keyboard() -> InlineKeyboardMarkup:
    """Кнопка отмены ввода токена."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="token:cancel")]
        ]
    )


def get_portfolio_keyboard(account_id: int, positions_count: int = 0) -> InlineKeyboardMarkup:
    """Интерактивное меню управления конкретным портфелем."""
    buttons = [
        [
            InlineKeyboardButton(text="🔄 Обновить", callback_data=f"portfolio:refresh:{account_id}"),
            InlineKeyboardButton(
                text=f"📦 Позиции ({positions_count})",
                callback_data=f"portfolio:positions:{account_id}",
            ),
        ],
        [
            InlineKeyboardButton(text="⚠️ Экспресс-аудит", callback_data=f"portfolio:audit:{account_id}"),
            InlineKeyboardButton(text="📑 Сменить счет", callback_data="portfolio:accounts"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_back_to_portfolio_keyboard(account_id: int) -> InlineKeyboardMarkup:
    """Кнопка возврата к сводке портфеля."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 К сводке портфеля", callback_data=f"portfolio:view:{account_id}")]
        ]
    )


def get_accounts_keyboard(accounts: list[dict]) -> InlineKeyboardMarkup:
    """Список счетов в виде инлайн-кнопок."""
    buttons = []
    for acc in accounts:
        acc_id = acc.get("id")
        name = acc.get("name", "Счет")
        buttons.append([
            InlineKeyboardButton(
                text=f"💼 {name} ({acc.get('account_id')})",
                callback_data=f"portfolio:view:{acc_id}",
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
