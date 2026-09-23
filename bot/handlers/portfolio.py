import asyncio
import logging
from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from bot.keyboards.inline_keyboards import (
    get_accounts_keyboard,
    get_back_to_portfolio_keyboard,
    get_portfolio_keyboard,
    get_positions_pagination_keyboard,
    get_tokens_keyboard,
)
from bot.lexicon.lexicon_ru import LEXICON_RU
from bot.services.api_client import BackendAPIClient
from bot.services.formatter import (
    build_portfolio_text,
    build_positions_text,
    build_risk_audit_text,
    build_analytics_text,
)

logger = logging.getLogger(__name__)
router = Router(name="portfolio_router")


async def _get_account_and_snapshot(
    api_client: BackendAPIClient,
    telegram_id: int,
    account_id: int | str | None = None,
) -> tuple[dict | None, dict | None, str | None]:
    """Вспомогательная функция извлечения счета и его последнего снимка с поддержкой консолидированного режима."""
    accounts = await api_client.get_accounts(telegram_id=telegram_id)
    if accounts is None:
        return None, None, LEXICON_RU["backend_error"]
    if not accounts:
        return None, None, LEXICON_RU["no_token_prompt"]

    is_consolidated = False
    if account_id is not None:
        if str(account_id).lower() == "consolidated":
            is_consolidated = True
    else:
        status = await api_client.check_user_status(telegram_id=telegram_id)
        if status and status.get("active_account_id") is None:
            is_consolidated = True

    if is_consolidated:
        target_acc = {
            "id": "consolidated",
            "name": "Все счета банка (Сводный)",
            "is_active": True,
        }
        snapshot = await api_client.get_consolidated_snapshot(telegram_id=telegram_id)
        if not snapshot:
            return target_acc, None, LEXICON_RU["no_snapshots_yet"]
        return target_acc, snapshot, None

    target_acc = None
    if account_id is not None and str(account_id).isdigit():
        target_acc = next((a for a in accounts if a.get("id") == int(account_id)), None)

    if target_acc is None:
        # 1. Приоритет: активный счет из базы данных
        target_acc = next((a for a in accounts if a.get("is_active")), None)
        # 2. Приоритет: счет с наибольшим балансом
        if target_acc is None:
            target_acc = max(accounts, key=lambda a: float(a.get("latest_balance") or 0))

    snapshot = await api_client.get_latest_snapshot(account_id=target_acc["id"])
    if not snapshot:
        return target_acc, None, LEXICON_RU["no_snapshots_yet"]

    return target_acc, snapshot, None


# ─────────────────────────────────────────────────────────────
# Обработчики Reply-кнопок главного меню
# ─────────────────────────────────────────────────────────────

@router.message(F.text == LEXICON_RU["btn_portfolio"])
async def process_portfolio_button(message: Message, api_client: BackendAPIClient):
    """Отображение главного дашборда портфеля с интерактивными кнопками."""
    account, snapshot, err = await _get_account_and_snapshot(
        api_client, telegram_id=message.from_user.id
    )

    if err:
        await message.answer(text=err, parse_mode="HTML")
        return

    text = build_portfolio_text(account, snapshot)
    positions_count = len(snapshot.get("positions", []))
    kb = get_portfolio_keyboard(account_id=account["id"], positions_count=positions_count)

    await message.answer(text=text, reply_markup=kb, parse_mode="HTML")


@router.message(F.text == LEXICON_RU["btn_accounts"])
async def process_accounts_button(message: Message, api_client: BackendAPIClient):
    """Вывод списка счетов с возможностью мгновенного переключения."""
    accounts = await api_client.get_accounts(telegram_id=message.from_user.id)
    if accounts is None:
        await message.answer(text=LEXICON_RU["backend_error"], parse_mode="HTML")
        return
    if not accounts:
        await message.answer(text=LEXICON_RU["no_token_prompt"], parse_mode="HTML")
        return

    status = await api_client.check_user_status(telegram_id=message.from_user.id)
    is_consolidated = bool(status and status.get("active_account_id") is None)
    kb = get_accounts_keyboard(accounts, is_consolidated_active=is_consolidated)
    await message.answer(
        text="📑 <b>Выберите брокерский счет для просмотра портфеля:</b>",
        reply_markup=kb,
        parse_mode="HTML",
    )


@router.message(F.text == LEXICON_RU["btn_sync"])
async def process_sync_button(message: Message, api_client: BackendAPIClient):
    """Запуск синхронизации с серверами Т-Банка."""
    wait_msg = await message.answer(
        "⏳ <i>Запрашиваю свежие котировки и балансы в Т-Банке...</i>",
        parse_mode="HTML",
    )
    success = await api_client.trigger_sync(telegram_id=message.from_user.id)
    if not success:
        await wait_msg.edit_text(text=LEXICON_RU["backend_error"], parse_mode="HTML")
        return

    # Даем фоновой задаче Celery 2 секунды на синхронизацию с gRPC API
    await asyncio.sleep(2.0)

    account, snapshot, _ = await _get_account_and_snapshot(
        api_client, telegram_id=message.from_user.id
    )
    if snapshot and account:
        text = build_portfolio_text(account, snapshot)
        positions_count = len(snapshot.get("positions", []))
        kb = get_portfolio_keyboard(account_id=account["id"], positions_count=positions_count)
        await wait_msg.edit_text(
            text=f"✅ <b>Данные успешно обновлены!</b>\n\n{text}",
            reply_markup=kb,
            parse_mode="HTML",
        )
    else:
        await wait_msg.edit_text(
            text="✅ <b>Синхронизация поставлена в очередь!</b> Нажмите «💼 Мой портфель» через пару секунд.",
            parse_mode="HTML",
        )


# ─────────────────────────────────────────────────────────────
# Inline Callback Query хэндлеры (Интерактивный дашборд)
# ─────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("portfolio:view:"))
async def cb_view_portfolio(callback: CallbackQuery, api_client: BackendAPIClient):
    """Возврат к карточке портфеля и фиксация активного счета."""
    acc_id_raw = callback.data.split(":")[2]

    # Запоминаем этот счет как активный на бэкенде
    await api_client.activate_account(telegram_id=callback.from_user.id, account_id=acc_id_raw)

    account, snapshot, err = await _get_account_and_snapshot(
        api_client, telegram_id=callback.from_user.id, account_id=acc_id_raw
    )
    if err:
        await callback.answer(err, show_alert=True)
        return

    text = build_portfolio_text(account, snapshot)
    positions_count = len(snapshot.get("positions", []))
    kb = get_portfolio_keyboard(account_id=account["id"], positions_count=positions_count)

    await callback.message.edit_text(text=text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("portfolio:refresh:"))
async def cb_refresh_portfolio(callback: CallbackQuery, api_client: BackendAPIClient):
    """Инлайн-обновление портфеля на лету без отправки новых сообщений."""
    acc_id_raw = callback.data.split(":")[2]
    await callback.answer("🔄 Запрашиваю свежие котировки...", show_alert=False)

    await api_client.trigger_sync(telegram_id=callback.from_user.id)
    await asyncio.sleep(2.0)

    account, snapshot, err = await _get_account_and_snapshot(
        api_client, telegram_id=callback.from_user.id, account_id=acc_id_raw
    )
    if snapshot and account:
        text = build_portfolio_text(account, snapshot)
        positions_count = len(snapshot.get("positions", []))
        kb = get_portfolio_keyboard(account_id=account["id"], positions_count=positions_count)
        try:
            await callback.message.edit_text(text=text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            pass


@router.callback_query(F.data.startswith("portfolio:positions:") | F.data.startswith("portfolio:pos:"))
async def cb_positions_portfolio(callback: CallbackQuery, api_client: BackendAPIClient):
    """Просмотр списка открытых позиций с пагинацией (по 5 на страницу)."""
    parts = callback.data.split(":")
    acc_id_raw = parts[2]
    page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 1

    account, snapshot, err = await _get_account_and_snapshot(
        api_client, telegram_id=callback.from_user.id, account_id=acc_id_raw
    )
    if err:
        await callback.answer(err, show_alert=True)
        return

    text, total_pages = build_positions_text(account, snapshot, page=page, page_size=5)
    kb = get_positions_pagination_keyboard(account_id=acc_id_raw, page=page, total_pages=total_pages)

    try:
        await callback.message.edit_text(text=text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data == "portfolio:accounts")
async def cb_accounts_portfolio(callback: CallbackQuery, api_client: BackendAPIClient):
    """Инлайн-переключение счета."""
    accounts = await api_client.get_accounts(telegram_id=callback.from_user.id)
    if not accounts:
        await callback.answer("Счета не найдены", show_alert=True)
        return

    status = await api_client.check_user_status(telegram_id=callback.from_user.id)
    is_consolidated = bool(status and status.get("active_account_id") is None)
    kb = get_accounts_keyboard(accounts, is_consolidated_active=is_consolidated)
    await callback.message.edit_text(
        text="📑 <b>Выберите брокерский счет для просмотра:</b>",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("portfolio:audit:"))
async def cb_audit_portfolio(callback: CallbackQuery, api_client: BackendAPIClient):
    """Экспресс-аудит риска и диверсификации на основе данных NumPy-движка."""
    acc_id_raw = callback.data.split(":")[2]

    await callback.answer("⏳ Провожу математический аудит...")

    if acc_id_raw == "consolidated":
        data = await api_client.get_consolidated_analytics(telegram_id=callback.from_user.id)
    else:
        data = await api_client.get_analytics(account_id=int(acc_id_raw))

    if data is None:
        await callback.message.edit_text(
            text=LEXICON_RU["backend_error"], 
            reply_markup=get_back_to_portfolio_keyboard(account_id=acc_id_raw),
            parse_mode="HTML",
        )
        return

    text = build_analytics_text(data)
    kb = get_back_to_portfolio_keyboard(account_id=acc_id_raw)
    await callback.message.edit_text(text=text, reply_markup=kb, parse_mode="HTML")



@router.callback_query(F.data == "tokens:menu")
async def cb_tokens_menu(callback: CallbackQuery, api_client: BackendAPIClient):
    """Меню управления токенами."""
    tokens = await api_client.get_tokens(telegram_id=callback.from_user.id)
    if tokens is None:
        await callback.answer(LEXICON_RU["backend_error"], show_alert=True)
        return

    kb = get_tokens_keyboard(tokens)
    text = (
        "🔑 <b>Управление токенами Т-Банка</b>\n\n"
        "Ниже представлены ваши привязанные токены. "
        "Нажмите на токен, чтобы сделать его активным:"
    )
    await callback.message.edit_text(text=text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("token:select:"))
async def cb_select_token(callback: CallbackQuery, api_client: BackendAPIClient):
    """Переключение активного токена."""
    token_id = int(callback.data.split(":")[2])
    await callback.answer("🔄 Переключаю активный портфель...", show_alert=False)

    ok = await api_client.activate_token(telegram_id=callback.from_user.id, token_id=token_id)
    if not ok:
        await callback.answer("Ошибка переключения токена", show_alert=True)
        return

    # Загружаем счета нового активного токена
    accounts = await api_client.get_accounts(telegram_id=callback.from_user.id)
    status = await api_client.check_user_status(telegram_id=callback.from_user.id)
    is_consolidated = bool(status and status.get("active_account_id") is None)
    kb = get_accounts_keyboard(accounts or [], is_consolidated_active=is_consolidated)
    await callback.message.edit_text(
        text="✅ <b>Активный токен переключен!</b>\n\nВыберите брокерский счет для просмотра:",
        reply_markup=kb,
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("token:active:"))
async def cb_active_token(callback: CallbackQuery):
    """Тост при клике на уже активный токен."""
    await callback.answer("✅ Этот токен уже выбран как активный.", show_alert=False)


@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery):
    """Пустой обработчик для информационных кнопок пагинатора."""
    await callback.answer()
