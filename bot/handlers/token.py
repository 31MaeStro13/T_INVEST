import logging
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.inline_keyboards import get_cancel_token_keyboard
from bot.lexicon.lexicon_ru import LEXICON_RU
from bot.services.api_client import BackendAPIClient
from bot.states.token_states import TokenState

logger = logging.getLogger(__name__)
router = Router(name="token_router")

# Список текстов кнопок главного меню для мгновенного сброса FSM
MAIN_MENU_BUTTONS = {
    LEXICON_RU["btn_portfolio"],
    LEXICON_RU["btn_accounts"],
    LEXICON_RU["btn_sync"],
    LEXICON_RU["btn_token"],
}


@router.message(F.text == LEXICON_RU["btn_token"])
async def process_token_button(message: Message, state: FSMContext):
    """Переход в режим ожидания ввода токена Т-Банка с кнопкой отмены."""
    await state.set_state(TokenState.waiting_for_token)
    await message.answer(
        text=LEXICON_RU["enter_token"],
        reply_markup=get_cancel_token_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "token:cancel")
async def process_token_cancel_callback(callback: CallbackQuery, state: FSMContext):
    """Отмена ввода токена по инлайн-кнопке."""
    await state.clear()
    await callback.answer("Ввод токена отменен")
    await callback.message.edit_text(
        "❌ <b>Ввод токена отменен.</b>\nВы можете продолжать работу через главное меню.",
        parse_mode="HTML",
    )


@router.message(TokenState.waiting_for_token)
async def process_token_input(
    message: Message, state: FSMContext, api_client: BackendAPIClient
):
    """
    Прием токена с защитой от FSM-ловушки и удалением секретного токена из переписки.
    """
    text = (message.text or "").strip()

    # 1. Защита от FSM-ловушки: если юзер нажал кнопку меню или команду
    if text in MAIN_MENU_BUTTONS or text in {"/cancel", "/start"}:
        await state.clear()
        if text == "/cancel":
            await message.answer("❌ <b>Ввод токена отменен.</b>", parse_mode="HTML")
            return
        # Для кнопок меню даем пользователю понятный ответ и инструкцию
        await message.answer(
            f"ℹ️ Ввод токена сброшен. Переключаю на <b>{text}</b>...",
            parse_mode="HTML",
        )
        # Импортируем хэндлеры для бесшовного выполнения команды
        from bot.handlers.portfolio import (
            process_accounts_button,
            process_portfolio_button,
            process_sync_button,
        )
        from bot.handlers.start import process_start_command

        if text == LEXICON_RU["btn_portfolio"]:
            await process_portfolio_button(message, api_client)
        elif text == LEXICON_RU["btn_accounts"]:
            await process_accounts_button(message, api_client)
        elif text == LEXICON_RU["btn_sync"]:
            await process_sync_button(message, api_client)
        elif text == "/start":
            await process_start_command(message)
        elif text == LEXICON_RU["btn_token"]:
            await process_token_button(message, state)
        return

    # 2. Валидация формата токена Т-Банка
    if not text.startswith("t."):
        await message.answer(
            text=LEXICON_RU["token_invalid"],
            reply_markup=get_cancel_token_keyboard(),
            parse_mode="HTML",
        )
        return

    # 3. Безопасность: немедленно удаляем сообщение с открытым токеном из чата
    try:
        await message.delete()
    except Exception as e:
        logger.warning("Не удалось удалить сообщение с токеном: %s", e)

    # 4. Сохраняем токен через API бэкенда (с автоматическим запуском Celery sync)
    wait_msg = await message.answer(
        "🔒 <i>Шифрую токен ключом Fernet и инициирую первичную синхронизацию...</i>",
        parse_mode="HTML",
    )

    success = await api_client.set_user_token(
        telegram_id=message.from_user.id,
        raw_token=text,
    )

    if success:
        await state.clear()
        await wait_msg.edit_text(
            text=LEXICON_RU["token_saved"],
            parse_mode="HTML",
        )
    else:
        await wait_msg.edit_text(
            text=LEXICON_RU["backend_error"],
            parse_mode="HTML",
        )
