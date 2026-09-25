from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def get_cancel_token_keyboard() -> InlineKeyboardMarkup:
    """Кнопка отмены ввода токена."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="token:cancel")]
        ]
    )


def get_portfolio_keyboard(account_id: int | str, positions_count: int = 0) -> InlineKeyboardMarkup:
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
            InlineKeyboardButton(text="📊 График", callback_data=f"portfolio:chart:{account_id}"),
            InlineKeyboardButton(text="⚠️ Экспресс-аудит", callback_data=f"portfolio:audit:{account_id}"),
        ],
        [
            InlineKeyboardButton(text="📑 Сменить счет", callback_data="portfolio:accounts"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_back_to_portfolio_keyboard(account_id: int | str) -> InlineKeyboardMarkup:
    """Кнопка возврата к сводке портфеля."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 К сводке портфеля", callback_data=f"portfolio:view:{account_id}")]
        ]
    )


def get_accounts_keyboard(accounts: list[dict], is_consolidated_active: bool = False) -> InlineKeyboardMarkup:
    """Список счетов в виде инлайн-кнопок с балансом и отметкой активного."""
    buttons = []

    # 1. Верхняя кнопка: Сводный портфель (Все счета)
    total_sum = sum(float(a.get("latest_balance") or 0) for a in accounts)
    cons_icon = "✅ " if is_consolidated_active else "🌐 "
    cons_balance = f" — {total_sum:,.0f} ₽".replace(",", " ") if total_sum > 0 else ""
    buttons.append([
        InlineKeyboardButton(
            text=f"{cons_icon}Все счета банка{cons_balance}",
            callback_data="portfolio:view:consolidated",
        )
    ])

    # 2. Индивидуальные счета
    for acc in accounts:
        acc_id = acc.get("id")
        name = acc.get("name", "Счет")
        is_active = acc.get("is_active", False) and not is_consolidated_active
        balance = acc.get("latest_balance")
        icon = "✅ " if is_active else "💼 "
        balance_str = f" — {balance:,.0f} ₽".replace(",", " ") if balance is not None else ""

        buttons.append([
            InlineKeyboardButton(
                text=f"{icon}{name}{balance_str}",
                callback_data=f"portfolio:view:{acc_id}",
            )
        ])

    buttons.append([
        InlineKeyboardButton(text="🔑 Мои токены Т-Банка", callback_data="tokens:menu")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_tokens_keyboard(tokens: list[dict]) -> InlineKeyboardMarkup:
    """Клавиатура управления мульти-токенами."""
    buttons = []
    for tok in tokens:
        tok_id = tok.get("id")
        name = tok.get("name", "Токен")
        is_active = tok.get("is_active", False)
        acc_cnt = tok.get("accounts_count", 0)

        if is_active:
            btn_text = f"✅ {name} ({acc_cnt} сч.) [Активен]"
            cb_data = f"token:active:{tok_id}"
        else:
            btn_text = f"▫️ {name} ({acc_cnt} сч.) — Включить"
            cb_data = f"token:select:{tok_id}"

        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=cb_data)])

    buttons.append([
        InlineKeyboardButton(text="➕ Добавить новый токен", callback_data="token:add"),
    ])
    buttons.append([
        InlineKeyboardButton(text="🔙 К выбору счетов", callback_data="portfolio:accounts"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_positions_pagination_keyboard(
    account_id: int | str, page: int, total_pages: int
) -> InlineKeyboardMarkup:
    """Клавиатура пагинации для длинного списка позиций."""
    nav_row = []
    if page > 1:
        nav_row.append(
            InlineKeyboardButton(text="⬅️ Назад", callback_data=f"portfolio:pos:{account_id}:{page - 1}")
        )

    nav_row.append(
        InlineKeyboardButton(text=f"Стр. {page}/{total_pages}", callback_data="noop")
    )

    if page < total_pages:
        nav_row.append(
            InlineKeyboardButton(text="Вперед ➡️", callback_data=f"portfolio:pos:{account_id}:{page + 1}")
        )

    buttons = [nav_row] if total_pages > 1 else []
    buttons.append([
        InlineKeyboardButton(text="🔙 К сводке портфеля", callback_data=f"portfolio:view:{account_id}")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
