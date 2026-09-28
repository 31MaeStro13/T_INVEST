import asyncio
import io
import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from bot.keyboards.inline_keyboards import (
    get_accounts_keyboard,
    get_ai_cancel_keyboard,
    get_back_to_portfolio_keyboard,
    get_cancel_upload_report_keyboard,
    get_delete_account_confirmation_keyboard,
    get_portfolio_keyboard,
    get_positions_pagination_keyboard,
    get_tokens_keyboard,
)
from bot.lexicon.lexicon_ru import LEXICON_RU
from bot.services.api_client import BackendAPIClient
from bot.services.formatter import (
    build_analytics_text,
    build_portfolio_text,
    build_positions_text,
)
from bot.states.ai_states import AIAuditorState
from bot.states.report_states import ReportUploadState

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
    status = await api_client.check_user_status(telegram_id=message.from_user.id)
    alerts_enabled = status.get("alerts_enabled", True) if status else True
    kb = get_portfolio_keyboard(
        account_id=account["id"],
        positions_count=positions_count,
        alerts_enabled=alerts_enabled,
    )

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
        text=LEXICON_RU["choose_account"],
        reply_markup=kb,
        parse_mode="HTML",
    )


@router.message(F.text == LEXICON_RU["btn_sync"])
async def process_sync_button(message: Message, api_client: BackendAPIClient):
    """Запуск синхронизации с серверами Т-Банка."""
    wait_msg = await message.answer(
        LEXICON_RU["sync_in_progress"],
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
            text=f"{LEXICON_RU['sync_success']}\n\n{text}",
            reply_markup=kb,
            parse_mode="HTML",
        )
    else:
        await wait_msg.edit_text(
            text=LEXICON_RU["sync_queued"],
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
    status = await api_client.check_user_status(telegram_id=callback.from_user.id)
    alerts_enabled = status.get("alerts_enabled", True) if status else True
    kb = get_portfolio_keyboard(
        account_id=account["id"],
        positions_count=positions_count,
        alerts_enabled=alerts_enabled,
    )

    await callback.message.edit_text(text=text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("portfolio:refresh:"))
async def cb_refresh_portfolio(callback: CallbackQuery, api_client: BackendAPIClient):
    """Инлайн-обновление портфеля на лету без отправки новых сообщений."""
    acc_id_raw = callback.data.split(":")[2]
    await callback.answer(LEXICON_RU["sync_toast"], show_alert=False)

    await api_client.trigger_sync(telegram_id=callback.from_user.id)
    await asyncio.sleep(2.0)

    account, snapshot, err = await _get_account_and_snapshot(
        api_client, telegram_id=callback.from_user.id, account_id=acc_id_raw
    )
    if snapshot and account:
        text = build_portfolio_text(account, snapshot)
        positions_count = len(snapshot.get("positions", []))
        status = await api_client.check_user_status(telegram_id=callback.from_user.id)
        alerts_enabled = status.get("alerts_enabled", True) if status else True
        kb = get_portfolio_keyboard(
            account_id=account["id"],
            positions_count=positions_count,
            alerts_enabled=alerts_enabled,
        )
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
        await callback.answer(LEXICON_RU["no_accounts_found"], show_alert=True)
        return

    status = await api_client.check_user_status(telegram_id=callback.from_user.id)
    is_consolidated = bool(status and status.get("active_account_id") is None)
    kb = get_accounts_keyboard(accounts, is_consolidated_active=is_consolidated)
    await callback.message.edit_text(
        text=LEXICON_RU["choose_account"],
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("portfolio:audit:"))
async def cb_audit_portfolio(callback: CallbackQuery, api_client: BackendAPIClient):
    """Экспресс-аудит риска и диверсификации на основе данных NumPy-движка."""
    acc_id_raw = callback.data.split(":")[2]

    await callback.answer(LEXICON_RU["audit_in_progress"])

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
    await callback.message.edit_text(text=LEXICON_RU["tokens_menu_title"], reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("token:select:"))
async def cb_select_token(callback: CallbackQuery, api_client: BackendAPIClient):
    """Переключение активного токена."""
    token_id = int(callback.data.split(":")[2])
    await callback.answer(LEXICON_RU["token_switch_toast"], show_alert=False)

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
        text=LEXICON_RU["token_switch_success"],
        reply_markup=kb,
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("token:active:"))
async def cb_active_token(callback: CallbackQuery):
    """Тост при клике на уже активный токен."""
    await callback.answer(LEXICON_RU["token_already_active"], show_alert=False)


@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery):
    """Пустой обработчик для информационных кнопок пагинатора."""
    await callback.answer()


@router.callback_query(F.data.startswith("portfolio:chart:"))
async def cb_chart_portfolio(callback: CallbackQuery, api_client: BackendAPIClient):
    """Генерация и отправка графического дашборда."""
    acc_id_raw = callback.data.split(":")[2]
    await callback.answer(LEXICON_RU["chart_generating"], show_alert=False)
    chart_bytes = await api_client.get_chart(
        account_id=acc_id_raw,
        telegram_id=callback.from_user.id,
    )
    if not chart_bytes:
        await callback.message.answer(
            text=LEXICON_RU["chart_error"],
            parse_mode="HTML",
        )
        return
    photo = BufferedInputFile(chart_bytes, filename=f"portfolio_{acc_id_raw}.png")
    caption = f"{LEXICON_RU['chart_caption']}{LEXICON_RU['disclaimer_safe_harbor']}"
    await callback.message.answer_photo(
        photo=photo,
        caption=caption,
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("portfolio:alerts:"))
async def cb_toggle_alerts(callback: CallbackQuery, api_client: BackendAPIClient):
    """Интерактивное переключение статуса риск-алертов."""
    acc_id_raw = callback.data.split(":")[2]
    new_status = await api_client.toggle_alerts(telegram_id=callback.from_user.id)
    if new_status is None:
        await callback.answer(LEXICON_RU["backend_error"], show_alert=True)
        return

    toast = LEXICON_RU["alerts_enabled_toast"] if new_status else LEXICON_RU["alerts_disabled_toast"]
    await callback.answer(toast, show_alert=False)

    _, snapshot, _ = await _get_account_and_snapshot(
        api_client, telegram_id=callback.from_user.id, account_id=acc_id_raw
    )
    positions_count = len(snapshot.get("positions", [])) if snapshot else 0

    kb = get_portfolio_keyboard(
        account_id=acc_id_raw,
        positions_count=positions_count,
        alerts_enabled=new_status,
    )
    try:
        await callback.message.edit_reply_markup(reply_markup=kb)
    except Exception:
        pass


@router.callback_query(F.data.startswith("portfolio:ask_ai:"))
async def cb_ask_ai_start(callback: CallbackQuery, state: FSMContext):
    """Инициализация диалога с AI-аудитором."""
    acc_id_raw = callback.data.split(":")[2]
    await state.set_state(AIAuditorState.waiting_for_question)
    await state.update_data(account_id=acc_id_raw)
    kb = get_ai_cancel_keyboard(account_id=acc_id_raw)
    await callback.message.answer(
        text=LEXICON_RU["ai_auditor_prompt"],
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ai:cancel:"))
async def cb_ask_ai_cancel(callback: CallbackQuery, state: FSMContext):
    """Отмена режима вопросов к AI-аудитору."""
    acc_id_raw = callback.data.split(":")[2]
    await state.clear()
    kb = get_back_to_portfolio_keyboard(account_id=acc_id_raw)
    await callback.message.edit_text(
        text=LEXICON_RU["ai_canceled"],
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AIAuditorState.waiting_for_question)
async def msg_ask_ai_process(message: Message, state: FSMContext, api_client: BackendAPIClient):
    """Обработка вопроса пользователя к AI-аудитору."""
    user_query = (message.text or "").strip()
    if not user_query:
        await message.answer("Пожалуйста, отправьте текстовый вопрос.")
        return

    data = await state.get_data()
    acc_id_raw = data.get("account_id", "consolidated")

    wait_msg = await message.answer(
        text=LEXICON_RU["ai_auditor_waiting"],
        parse_mode="HTML",
    )

    try:
        answer = await api_client.ask_ai_auditor(
            telegram_id=message.from_user.id,
            prompt=user_query,
        )
    except Exception as exc:
        logger.exception("Ошибка при вызове AI-аудитора: %s", exc)
        answer = "⚠️ Произошла ошибка при анализе портфеля. Попробуйте позже."

    try:
        await wait_msg.delete()
    except Exception:
        pass

    kb = get_back_to_portfolio_keyboard(account_id=acc_id_raw)

    import html
    # Очищаем от случайных маркдаун-символов
    clean_answer = (
        answer.replace("###", "")
        .replace("##", "")
        .replace("#", "")
        .replace("**", "")
        .replace("*", "")
        .strip()
    )
    escaped_answer = html.escape(clean_answer)
    full_text = f"{escaped_answer}{LEXICON_RU['disclaimer_safe_harbor']}"

    # Telegram limit 4096 chars
    if len(full_text) > 4000:
        full_text = full_text[:3990] + "...\n[Сообщение сокращено]"

    try:
        await message.answer(text=full_text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await message.answer(text=full_text, reply_markup=kb, parse_mode=None)

    await state.clear()



@router.callback_query(F.data == "account:ask_delete")
async def cb_ask_delete_account(callback: CallbackQuery):
    """Предупреждение перед полным удалением аккаунта (152-ФЗ / GDPR)."""
    text = (
        "⚠️ <b>ВНИМАНИЕ! Безвозвратное удаление данных (152-ФЗ / GDPR)</b>\n\n"
        "Вы запрашиваете полное удаление своего профиля:\n"
        "• Все зашифрованные токены Т-Банка будут стерты.\n"
        "• Все брокерские счета, позиции и история снимков будут удалены.\n"
        "• Кэш аналитики и графиков будет очищен.\n"
        "• Zero-Knowledge идентификатор будет аннулирован.\n\n"
        "<b>Это действие необратимо.</b> Вы уверены?"
    )
    await callback.message.edit_text(
        text=text,
        reply_markup=get_delete_account_confirmation_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "account:confirm_delete")
async def cb_confirm_delete_account(callback: CallbackQuery, api_client: BackendAPIClient):
    """Подтвержденное удаление аккаунта."""
    ok = await api_client.delete_account(telegram_id=callback.from_user.id)
    if ok:
        await callback.message.edit_text(
            text=(
                "✅ <b>Ваши данные успешно удалены</b>\n\n"
                "В соответствии с 152-ФЗ и GDPR Right to be Forgotten все ваши брокерские токены, "
                "история портфелей и кэш безвозвратно стерты.\n\n"
                "Чтобы начать заново, отправьте команду /start."
            ),
            reply_markup=None,
            parse_mode="HTML",
        )
    else:
        await callback.message.edit_text(
            text="⚠️ Не удалось удалить данные или аккаунт уже был удален. Попробуйте снова или обратитесь в поддержку.",
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data == "report:upload")
async def cb_report_upload_start(callback: CallbackQuery, state: FSMContext):
    """Запуск загрузки брокерского отчета Excel."""
    await state.set_state(ReportUploadState.waiting_for_file)
    text = (
        "📄 <b>Экспресс-анализ брокерского отчета (.xlsx)</b>\n\n"
        "Вы можете получить полный аудит портфеля <b>без привязки токена</b>!\n\n"
        "🛡 <b>Принцип Zero-Disk:</b>\n"
        "• Файл обрабатывается исключительно в оперативной памяти (RAM).\n"
        "• Ни байта не записывается на диск или в базу данных.\n"
        "• Номера счетов и персональные данные не сохраняются.\n\n"
        "📎 <b>Отправьте файл отчета (.xlsx) в ответ на это сообщение:</b>"
    )
    await callback.message.answer(
        text=text,
        reply_markup=get_cancel_upload_report_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "report:cancel")
async def cb_report_cancel(callback: CallbackQuery, state: FSMContext):
    """Отмена загрузки отчета."""
    await state.clear()
    await callback.answer("Загрузка отчета отменена")
    await callback.message.edit_text("❌ Загрузка брокерского отчета отменена.", parse_mode="HTML")


@router.message(ReportUploadState.waiting_for_file, F.document)
async def process_report_file(
    message: Message, state: FSMContext, api_client: BackendAPIClient, bot: Bot
):
    """Прием и In-Memory анализ файла отчета."""
    doc = message.document
    filename = doc.file_name or "report.xlsx"

    if not filename.lower().endswith(".xlsx"):
        await message.answer(
            "⚠️ Пожалуйста, отправьте файл в формате Excel (.xlsx). Другие форматы пока не поддерживаются.",
            reply_markup=get_cancel_upload_report_keyboard(),
        )
        return

    wait_msg = await message.answer(
        "⏳ <i>Читаю отчет в оперативной памяти (RAM) и рассчитываю метрики концентрации и риска...</i>",
        parse_mode="HTML",
    )

    try:
        file_io = io.BytesIO()
        await bot.download(doc, destination=file_io)
        file_bytes = file_io.getvalue()

        data = await api_client.upload_broker_report(file_bytes=file_bytes, filename=filename)
        await state.clear()

        if not data or data.get("status") != "success":
            detail = data.get("detail", "Не удалось распознать формат таблицы.") if data else "Ошибка связи с сервером."
            await wait_msg.edit_text(f"❌ Ошибка анализа отчета: {detail}", parse_mode="HTML")
            return

        total = data.get("total_amount_portfolio", 0)
        pos_cnt = data.get("positions_count", 0)
        risk = data.get("risk_metrics", {})
        hhi = risk.get("hhi_index", 0)
        risk_label = risk.get("concentration_label", "")
        top_share = risk.get("top_asset_share_pct", 0)
        breakdown = data.get("asset_percentages", {})

        report_text = (
            f"📊 <b>Результаты экспресс-аудита отчета</b>\n"
            f"📁 <i>Файл: {filename} (Zero-Disk RAM)</i>\n\n"
            f"💰 <b>Стоимость портфеля:</b> {total:,.2f} ₽\n"
            f"📦 <b>Всего позиций:</b> {pos_cnt} шт.\n\n"
            f"<b>Структура активов:</b>\n"
            f"• Акции: {breakdown.get('shares', 0)}%\n"
            f"• Облигации: {breakdown.get('bonds', 0)}%\n"
            f"• Фонды (ETF): {breakdown.get('etf', 0)}%\n"
            f"• Валюта: {breakdown.get('currencies', 0)}%\n\n"
            f"<b>Оценка диверсификации:</b>\n"
            f"• Индекс Герфиндаля-Хиршмана (HHI): <b>{hhi}</b>\n"
            f"• Статус риска: <b>{risk_label}</b>\n"
            f"• Крупнейшая позиция: <b>{top_share}%</b> портфеля\n\n"
            f"🔒 <i>Файл удален из оперативной памяти сразу после обработки. Ваши токены и ключи не требовались.</i>"
        )
        await wait_msg.edit_text(report_text, parse_mode="HTML")

    except Exception as exc:
        logger.error(f"Сбой загрузки отчета: {exc}")
        await state.clear()
        await wait_msg.edit_text("❌ Произошла ошибка при обработке файла отчета.", parse_mode="HTML")



