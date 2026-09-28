"""
throttling.py — Кастомные Rate Limiter-ы для защиты дорогостоящих AI-эндпоинтов.

Использует Redis через Django Cache framework.
Лимит AI-аудитора: 5 запросов в час на Telegram ID.
"""
from rest_framework.throttling import SimpleRateThrottle


class AiAuditorRateThrottle(SimpleRateThrottle):
    """
    Лимит запросов к AI-аудитору: 5 в час на одного пользователя (по telegram_id).

    Почему по telegram_id, а не по IP:
    - Бот работает как прокси: все запросы приходят с одного IP (бот-сервера).
    - Per-user лимит справедлив и сложнее обойти.
    """

    scope = "ai_auditor"

    def get_cache_key(self, request, view) -> str | None:
        # Для POST-запросов telegram_id лежит в теле
        telegram_id = request.data.get("telegram_id")
        if not telegram_id:
            # Фоллбэк на IP если telegram_id не передан
            return self.get_ident(request)
        return self.cache_format % {
            "scope": self.scope,
            "ident": str(telegram_id),
        }
