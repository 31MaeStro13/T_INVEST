import time
from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.lexicon.lexicon_ru import LEXICON_RU


class ThrottlingMiddleware(BaseMiddleware):
    """
    Антиспам middleware: ограничивает частоту запросов от одного пользователя.
    Поддерживает как Message, так и CallbackQuery (инлайн-кнопки).
    Включает теневой бан (silent drop) при агрессивном спаме.
    """

    def __init__(self, rate_limit: float = 1.0, ban_threshold: int = 5, ban_time: float = 30.0):
        self.rate_limit = rate_limit
        self.ban_threshold = ban_threshold
        self.ban_time = ban_time

        self.last_action: Dict[int, float] = {}
        self.violations: Dict[int, int] = {}
        self.banned_until: Dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if not user:
            return await handler(event, data)

        user_id = user.id
        current_time = time.time()

        # 1. Проверка активного теневого бана (Silent Drop)
        if current_time < self.banned_until.get(user_id, 0.0):
            if isinstance(event, CallbackQuery):
                await event.answer()  # Гасим спиннер кнопки без траты ресурсов
            return

        last_time = self.last_action.get(user_id, 0.0)

        # 2. Если между запросами прошло меньше rate_limit
        if current_time - last_time < self.rate_limit:
            count = self.violations.get(user_id, 0) + 1
            self.violations[user_id] = count

            # При агрессивном спаме включаем теневой бан
            if count >= self.ban_threshold:
                self.banned_until[user_id] = current_time + self.ban_time
                self.violations[user_id] = 0
                if isinstance(event, CallbackQuery):
                    await event.answer("⚠️ Слишком много запросов. Подождите 30 сек.", show_alert=True)
                elif isinstance(event, Message):
                    await event.answer("⚠️ <i>Слишком много запросов. Бот временно приостановил обработку на 30 сек.</i>", parse_mode="HTML")
                return

            # Предупреждение (тост для инлайн-кнопок, сообщение для текста)
            if isinstance(event, CallbackQuery):
                await event.answer(LEXICON_RU["throttle_toast"], show_alert=True)
            elif isinstance(event, Message):
                if count == 1:
                    await event.answer(LEXICON_RU["throttle_message"], parse_mode="HTML")
            return

        # Успешный запрос — сбрасываем счетчик нарушений
        self.last_action[user_id] = current_time
        self.violations[user_id] = 0

        return await handler(event, data)
