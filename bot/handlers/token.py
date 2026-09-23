import logging
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.inline_keyboards import (
    get_cancel_token_keyboard,
    get_tokens_keyboard,
)
from bot.lexicon.lexicon_ru import LEXICON_RU
from bot.services.api_client import BackendAPIClient
from bot.states.token_states import TokenState

logger = logging.getLogger(__name__)
router = Router(name="token_router")

MAIN_MENU_BUTTONS = {
    LEXICON_RU["btn_portfolio"],
    LEXICON_RU["btn_accounts"],
    LEXICON_RU["btn_sync"],
    LEXICON_RU["btn_token"],
}


@router.message(F.text == LEXICON_RU["btn_token"])
async def process_token_button(
    message: Message, state: FSMContext, api_client: BackendAPIClient
):
    """Показывает меню управления токенами либо переходит к вводу первого токена."""
    tokens = await api_client.get_tokens(telegram_id=message.from_user.id)

    if tokens:
        kb = get_tokens_keyboard(tokens)
        await message.answer(
            text="🔑 <b>Управление токенами Т-Банка</b>\n\n"
                 "Ниже представлены ваши привязанные токены. "
                 "Вы можете переключаться между ними в один клик или добавить новый:",
            reply_markup=kb,
            parse_mode="HTML",
        )
    else:
        await state.set_state(TokenState.waiting_for_token)
        await message.answer(
            text=LEXICON_RU["enter_token"],
            reply_markup=get_cancel_token_keyboard(),
            parse_mode="HTML",
        )


@router.callback_query(F.data == "token:add")
async def process_token_add_callback(callback: CallbackQuery, state: FSMContext):
    """Старт добавления нового токена по инлайн-кнопке."""
    await state.set_state(TokenState.waiting_for_token)
    await callback.message.answer(
        text=LEXICON_RU["enter_token"],
        reply_markup=get_cancel_token_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


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
    """Прием токена с валидацией, удалением из чата и переходом к запросу имени."""
    text = (message.text or "").strip()

    # 1. Защита от FSM-ловушки
    if text in MAIN_MENU_BUTTONS or text in {"/cancel", "/start"}:
        await state.clear()
        if text == "/cancel":
            await message.answer("❌ <b>Ввод токена отменен.</b>", parse_mode="HTML")
            return
        await message.answer(
            f"ℹ️ Ввод токена сброшен. Переключаю на <b>{text}</b>...",
            parse_mode="HTML",
        )
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
            await process_token_button(message, state, api_client)
        return

    # 2. Валидация формата токена
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

    # 4. Сохраняем токен во временное состояние и запрашиваем понятное имя
    await state.update_data(raw_token=text)
    await state.set_state(TokenState.waiting_for_name)

    await message.answer(
        "🏷 <b>Как назвать этот портфель?</b>\n\n"
        "Отправьте понятное имя (например: <i>«Личный»</i>, <i>«Портфель Олега»</i>, <i>«Инвест-клуб»</i>):\n"
        "<i>(Или отправьте точку <code>.</code>, чтобы использовать стандартное имя)</i>",
        reply_markup=get_cancel_token_keyboard(),
        parse_mode="HTML",
    )


@router.message(TokenState.waiting_for_name)
async def process_token_name_input(
    message: Message, state: FSMContext, api_client: BackendAPIClient
):
    """Прием имени токена, шифрование и запуск синхронизации."""
    text = (message.text or "").strip()

    if text in MAIN_MENU_BUTTONS or text in {"/cancel", "/start"}:
        await state.clear()
        await message.answer("❌ <b>Привязка токена отменена.</b>", parse_mode="HTML")
        return

    name = "Основной портфель" if text == "." or not text else text[:48]

    data = await state.get_data()
    raw_token = data.get("raw_token")

    if not raw_token:
        await state.clear()
        await message.answer("❌ Ошибка: токен не найден в сессии. Попробуйте снова.")
        return

    wait_msg = await message.answer(
        f"🔒 <i>Шифрую токен «{name}» ключом Fernet и запускаю синхронизацию с Т-Банком...</i>",
        parse_mode="HTML",
    )

    success = await api_client.set_user_token(
        telegram_id=message.from_user.id,
        raw_token=raw_token,
        name=name,
    )

    await state.clear()

    if success:
        await wait_msg.edit_text(
            f"✅ <b>Портфель «{name}» успешно привязан!</b>\n\n"
            "Синхронизация счетов запущена в фоне. Через несколько секунд нажмите "
            "<b>«💼 Мой портфель»</b> или <b>«📑 Счета»</b>.",
            parse_mode="HTML",
        )
    else:
        await wait_msg.edit_text(
            text=LEXICON_RU["backend_error"],
            parse_mode="HTML",
        )
