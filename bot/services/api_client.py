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

    async def get_consolidated_snapshot(self, telegram_id: int) -> dict[str, Any] | None:
        """Получает агрегированный снимок портфеля по всем счетам пользователя."""
        url = f"{self.base_url}/api/v1/accounts/consolidated_snapshot/"
        params = {"telegram_id": telegram_id}
        try:
            async with self.session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                if response.status == 200:
                    return await response.json()
                logger.warning(f"Ошибка получения сводного снимка (status {response.status})")
                return None
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.error(f"Сбой подключения к бэкенду (get_consolidated_snapshot): {exc}")
            return None

    async def get_analytics(self, account_id: int) -> dict | None:
        url = f"{self.base_url}/api/v1/analytics/{account_id}/"
        try:
            async with self.session.get(
                url, timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                if response.status == 200:
                    return await response.json()
                return None
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.error(f"Сбой подключения к бэкенду (get_analytics): {exc}")
            return None

    async def get_consolidated_analytics(self, telegram_id: int) -> dict | None:
        """Получает консолидированную аналитику и риск-аудит по всем счетам."""
        url = f"{self.base_url}/api/v1/analytics/consolidated/"
        params = {"telegram_id": telegram_id}
        try:
            async with self.session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                if response.status == 200:
                    return await response.json()
                return None
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.error(f"Сбой подключения к бэкенду (get_consolidated_analytics): {exc}")
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

    async def get_tokens(self, telegram_id: int) -> list[dict[str, Any]] | None:
        """Получает список всех токенов пользователя."""
        url = f"{self.base_url}/api/v1/tokens/"
        params = {"telegram_id": telegram_id}
        try:
            async with self.session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                if response.status == 200:
                    return await response.json()
                return None
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.error(f"Сбой подключения к бэкенду (get_tokens): {exc}")
            return None

    async def set_user_token(self, telegram_id: int, raw_token: str, name: str = "Основной портфель") -> bool:
        """Отправляет токен Т-Банка на бэкенд для шифрования и сохранения."""
        url = f"{self.base_url}/api/v1/users/token/"
        payload = {"telegram_id": telegram_id, "token": raw_token, "name": name}
        try:
            async with self.session.post(
                url, json=payload, timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                if response.status == 200:
                    logger.info(f"Токен '{name}' для telegram_id={telegram_id} успешно сохранен.")
                    return True
                logger.warning(f"Ошибка сохранения токена: status {response.status}")
                return False
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.error(f"Сбой подключения к бэкенду (set_user_token): {exc}")
            return False

    async def activate_token(self, telegram_id: int, token_id: int) -> bool:
        """Активирует выбранный токен пользователя."""
        url = f"{self.base_url}/api/v1/tokens/{token_id}/activate/"
        payload = {"telegram_id": telegram_id}
        try:
            async with self.session.post(
                url, json=payload, timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                return response.status == 200
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.error(f"Сбой подключения к бэкенду (activate_token): {exc}")
            return False

    async def activate_account(self, telegram_id: int, account_id: int | str) -> bool:
        """Делает брокерский счет (или режим 'Все счета') активным."""
        try:
            if str(account_id).lower() in ("consolidated", "all", "none", "0"):
                url = f"{self.base_url}/api/v1/accounts/activate_consolidated/"
                payload = {"telegram_id": telegram_id}
                async with self.session.post(
                    url, json=payload, timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    return response.status == 200
            else:
                url = f"{self.base_url}/api/v1/accounts/{account_id}/activate/"
                async with self.session.post(
                    url, timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    return response.status == 200
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.error(f"Сбой подключения к бэкенду (activate_account): {exc}")
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

    async def get_chart(self, account_id: int | str, telegram_id: int) -> bytes | None:
        """Скачивает бинарные байты PNG-дашборда из бэкенда."""
        
        if str(account_id).lower() == "consolidated":
            url = f"{self.base_url}/api/v1/analytics/consolidated/chart/"
            params = {"telegram_id": telegram_id}

        else:
            url = f"{self.base_url}/api/v1/analytics/{account_id}/chart/"
            params = {}

        try: 
            async with self.session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 200:
                    return await response.read()
                return None 
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.error(f"Сбой загрузки графика (get_chart): {exc}")
            return None

    async def toggle_alerts(self, telegram_id: int) -> bool | None:
        """Переключает статус риск-алертов пользователя."""
        url = f"{self.base_url}/api/v1/users/toggle_alerts/"
        payload = {"telegram_id": telegram_id}
        try:
            async with self.session.post(
                url, json=payload, timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("alerts_enabled")
                return None
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.error(f"Сбой переключения алертов (toggle_alerts): {exc}")
            return None

    async def ask_ai_auditor(self, telegram_id: int, prompt: str) -> str:
        """Отправляет запрос к AI-агенту финансового аудита на базе Agno."""
        url = f"{self.base_url}/api/v1/analytics/ask_ai/"
        payload = {"telegram_id": telegram_id, "prompt": prompt}
        try:
            async with self.session.post(
                url, json=payload, timeout=aiohttp.ClientTimeout(total=45)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("response", "Не удалось получить ответ.")
                logger.warning(f"Ошибка ответа AI-агента: статус {response.status}")
                return "⚠️ Не удалось получить ответ от AI-агента. Попробуйте позже."
        except asyncio.TimeoutError:
            return "⏳ AI-агент обрабатывает запрос слишком долго. Пожалуйста, попробуйте сформулировать вопрос короче."
        except aiohttp.ClientError as exc:
            logger.error(f"Сбой подключения к бэкенду (ask_ai_auditor): {exc}")
            return "⚠️ Ошибка связи с сервером AI-аналитики."


