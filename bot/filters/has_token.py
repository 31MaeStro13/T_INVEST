from aiogram.filters import BaseFilter
from aiogram.types import Message
from bot.services.api_client import BackendAPIClient


class HasTokenFilter(BaseFilter):
    """Фильтр: пропускает сообщение только если у пользователя привязан токен."""

    async def __call__(self, message: Message, api_client: BackendAPIClient) -> bool:
        if not message.from_user:
            return False
        status = await api_client.check_user_status(message.from_user.id)
        return bool(status and status.get("has_token"))
