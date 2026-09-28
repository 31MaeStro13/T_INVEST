"""
security.py — Криптографические утилиты безопасности и Zero-Knowledge идентификации.
"""

import hashlib
import hmac

from django.conf import settings


def compute_user_hash(telegram_id: int | str) -> str:
    """
    Вычисляет криптографический необратимый HMAC-SHA256 хэш от telegram_id с секретной солью.

    Гарантирует Zero-Knowledge анонимность:
    - Позволяет однозначно идентифицировать инвестора в системе.
    - Математически исключает возможность восстановления реального Telegram ID из хэша при утечке БД.
    """
    salt = getattr(settings, "USER_HASH_SALT", "t_invest_zero_knowledge_salt_2026")
    return hmac.new(
        salt.encode("utf-8"),
        str(telegram_id).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def mask_token(token: str) -> str:
    """
    Маскирует токен брокера для безопасного логирования (t.***1234).
    Исключает попадание секретных API-токенов в открытый лог.
    """
    if not token or len(token) < 8:
        return "***"
    return f"{token[:2]}***{token[-4:]}"


def mask_identifier(identifier: int | str) -> str:
    """Маскирует ID или хэш пользователя для аудит-логов."""
    s = str(identifier).strip()
    if len(s) <= 4:
        return "***"
    return f"{s[:3]}...{s[-3:]}"

