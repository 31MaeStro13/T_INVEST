import asyncio
import logging
from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from bot.keyboards.inline_keyboards import (
    get_accounts_keyboard,
    get_back_to_portfolio_keyboard,
    get_portfolio_keyboard,
)
from bot.lexicon.lexicon_ru import LEXICON_RU
from bot.services.api_client import BackendAPIClient
from bot.services.formatter import (
    build_portfolio_text,
    build_positions_text,
    build_risk_audit_text,
)

logger = logging.getLogger(__name__)
router = Router(name="portfolio_router")


async def _get_account_and_snapshot(
    api_client: BackendAPIClient,
    telegram_id: int,
    account_id: int | None = None,
) -> tuple[dict | None, dict | None, str | None]:
    """Вспомогательная функция извлечения счета и его последнего снимка."""
    accounts = await api_client.get_accounts(telegram_id=telegram_id)
    if accounts is None:
        return None, None, LEXICON_RU["backend_error"]
    if not accounts:
        return None, None, LEXICON_RU["no_token_prompt"]

    target_acc = None
    if account_id is not None:
        for acc in accounts:
            if acc.get("id") == account_id:
                target_acc = acc
                break

    if target_acc is None:
        target_acc = accounts[0]

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

    kb = get_accounts_keyboard(accounts)
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
    """Возврат к карточке портфеля."""
    acc_id = int(callback.data.split(":")[2])
    account, snapshot, err = await _get_account_and_snapshot(
        api_client, telegram_id=callback.from_user.id, account_id=acc_id
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
    acc_id = int(callback.data.split(":")[2])
    await callback.answer("🔄 Запрашиваю свежие котировки...", show_alert=False)

    await api_client.trigger_sync(telegram_id=callback.from_user.id)
    await asyncio.sleep(2.0)

    account, snapshot, err = await _get_account_and_snapshot(
        api_client, telegram_id=callback.from_user.id, account_id=acc_id
    )
    if snapshot and account:
        text = build_portfolio_text(account, snapshot)
        positions_count = len(snapshot.get("positions", []))
        kb = get_portfolio_keyboard(account_id=account["id"], positions_count=positions_count)
        try:
            await callback.message.edit_text(text=text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            # Если текст сообщения не изменился (котировки те же)
            pass


@router.callback_query(F.data.startswith("portfolio:positions:"))
async def cb_positions_portfolio(callback: CallbackQuery, api_client: BackendAPIClient):
    """Просмотр детального списка открытых позиций."""
    acc_id = int(callback.data.split(":")[2])
    account, snapshot, err = await _get_account_and_snapshot(
        api_client, telegram_id=callback.from_user.id, account_id=acc_id
    )
    if err:
        await callback.answer(err, show_alert=True)
        return

    text = build_positions_text(account, snapshot)
    kb = get_back_to_portfolio_keyboard(account_id=acc_id)
    await callback.message.edit_text(text=text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("portfolio:audit:"))
async def cb_audit_portfolio(callback: CallbackQuery, api_client: BackendAPIClient):
    """Экспресс-аудит риска и диверсификации."""
    acc_id = int(callback.data.split(":")[2])
    account, snapshot, err = await _get_account_and_snapshot(
        api_client, telegram_id=callback.from_user.id, account_id=acc_id
    )
    if err:
        await callback.answer(err, show_alert=True)
        return

    text = build_risk_audit_text(account, snapshot)
    kb = get_back_to_portfolio_keyboard(account_id=acc_id)
    await callback.message.edit_text(text=text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "portfolio:accounts")
async def cb_accounts_portfolio(callback: CallbackQuery, api_client: BackendAPIClient):
    """Инлайн-переключение счета."""
    accounts = await api_client.get_accounts(telegram_id=callback.from_user.id)
    if not accounts:
        await callback.answer("Счета не найдены", show_alert=True)
        return

    kb = get_accounts_keyboard(accounts)
    await callback.message.edit_text(
        text="📑 <b>Выберите брокерский счет для просмотра:</b>",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()
