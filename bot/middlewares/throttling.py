import time
from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject


class ThrottlingMiddleware(BaseMiddleware):
    """
    Антиспам middleware: ограничивает частоту нажатия кнопок от одного пользователя.
    По умолчанию: не чаще 1 запроса в секунду.
    """

    def __init__(self, rate_limit: float = 1.0):
        self.rate_limit = rate_limit
        self.cache: Dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
            current_time = time.time()
            last_time = self.cache.get(user_id, 0.0)

            if current_time - last_time < self.rate_limit:
                # Превышен лимит нажатия
                await event.answer("⏱ <i>Пожалуйста, не нажимайте кнопки слишком часто.</i>", parse_mode="HTML")
                return

            self.cache[user_id] = current_time

        return await handler(event, data)
