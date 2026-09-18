import asyncio
import logging
from typing import Any
import aiohttp

logger = logging.getLogger(__name__)


class BackendAPIClient:
    """Асинхронный HTTP-клиент для взаимодействия с Django REST API."""

    def __init__(self, base_url: str, session: aiohttp.ClientSession):
        self.base_url = base_url.rstrip("/")
        self.session = session

    async def get_accounts(self, telegram_id: int | None = None) -> list[dict[str, Any]] | None:
        """Получает брокерские счета (с фильтрацией по telegram_id)."""
        url = f"{self.base_url}/api/v1/accounts/"
        params = {"telegram_id": telegram_id} if telegram_id else {}
        try:
            async with self.session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                if response.status == 200:
                    return await response.json()
                logger.warning(f"Ошибка получения счетов (status {response.status})")
                return None
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.error(f"Сбой подключения к бэкенду (get_accounts): {exc}")
            return None

    async def get_latest_snapshot(self, account_id: int) -> dict[str, Any] | None:
        """Получает последний снимок портфеля с позициями для счета."""
        url = f"{self.base_url}/api/v1/accounts/{account_id}/latest_snapshot/"
        try:
            async with self.session.get(
                url, timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                if response.status == 200:
                    return await response.json()
                logger.warning(
                    f"Ошибка получения снимка для счета {account_id} (status {response.status})"
                )
                return None
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.error(f"Сбой подключения к бэкенду (get_latest_snapshot): {exc}")
            return None

    async def check_user_status(self, telegram_id: int) -> dict[str, Any] | None:
        """Проверяет статус пользователя (зарегистрирован ли, привязан ли токен)."""
        url = f"{self.base_url}/api/v1/users/status/"
        params = {"telegram_id": telegram_id}
        try:
            async with self.session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                if response.status == 200:
                    return await response.json()
                return None
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.error(f"Сбой подключения к бэкенду (check_user_status): {exc}")
            return None

    async def set_user_token(self, telegram_id: int, raw_token: str) -> bool:
        """Отправляет токен Т-Банка на бэкенд для шифрования и сохранения."""
        url = f"{self.base_url}/api/v1/users/token/"
        payload = {"telegram_id": telegram_id, "token": raw_token}
        try:
            async with self.session.post(
                url, json=payload, timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                if response.status == 200:
                    logger.info(f"Токен для telegram_id={telegram_id} успешно сохранен на бэкенде.")
                    return True
                logger.warning(f"Ошибка сохранения токена: status {response.status}")
                return False
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.error(f"Сбой подключения к бэкенду (set_user_token): {exc}")
            return False

    async def trigger_sync(self, telegram_id: int) -> bool:
        """Запускает внеочередную задачу синхронизации портфеля в Celery."""
        url = f"{self.base_url}/api/v1/users/sync/"
        payload = {"telegram_id": telegram_id}
        try:
            async with self.session.post(
                url, json=payload, timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                if response.status == 200:
                    logger.info(f"Синхронизация для telegram_id={telegram_id} отправлена в очередь.")
                    return True
                logger.warning(f"Ошибка триггера синхронизации: status {response.status}")
                return False
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.error(f"Сбой подключения к бэкенду (trigger_sync): {exc}")
            return False
