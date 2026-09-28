
import logging
import os

import requests as http_requests
from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from t_tech.invest import Client
from t_tech.invest.exceptions import RequestError
from users.models import InvestorUser

from .models import Account, PortfolioSnapshot
from .services import save_portfolio_snapshot

logger = logging.getLogger(__name__)


def _deactivate_token_and_notify(token_obj, user: InvestorUser) -> None:
    """
    При получении 401 от Т-Банка:
    1. Деактивирует токен (is_active = False) в БД.
    2. Отправляет push-уведомление пользователю через Telegram Bot API.

    Вызывается из Celery воркера напрямую — без HTTP к бэкенду,
    так как мы уже внутри Django-контекста.
    """
    # 1. Деактивировать токен
    try:
        if hasattr(token_obj, "is_active"):
            # Это BrokerToken
            token_obj.is_active = False
            token_obj.save(update_fields=["is_active"])
            logger.info("🔒 Токен #%d пользователя #%d деактивирован.", token_obj.id, user.id)
        else:
            # Это сам InvestorUser с encrypted_token — очищаем
            user.encrypted_token = ""
            user.save(update_fields=["encrypted_token"])
            logger.info("🔒 Токен пользователя #%d очищен.", user.id)
    except Exception as exc:
        logger.error("Ошибка при деактивации токена: %s", exc)

    # 2. Telegram push-уведомление
    bot_token = getattr(settings, "TELEGRAM_BOT_TOKEN", "") or os.getenv("BOT_TOKEN", "")
    if not bot_token or not user.telegram_id:
        logger.warning(
            "Не удалось отправить уведомление: BOT_TOKEN или telegram_id отсутствует."
        )
        return

    text = (
        "⚠️ <b>Ваш токен Т-Инвестиций устарел или был отозван.</b>\n\n"
        "Синхронизация портфеля приостановлена.\n\n"
        "Пожалуйста, обновите токен:\n"
        "1️⃣ Откройте Т-Инвестиции\n"
        "2️⃣ Перейдите в <b>Настройки → API-токен</b>\n"
        "3️⃣ Скопируйте новый токен и отправьте его мне через /start\n\n"
        "Ваши исторические данные портфеля сохранены."
    )

    try:
        resp = http_requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={
                "chat_id": user.telegram_id,
                "text": text,
                "parse_mode": "HTML",
            },
            timeout=10,
        )
        if resp.status_code == 200:
            logger.info("📬 Уведомление об устаревшем токене отправлено пользователю #%d.", user.id)
        else:
            logger.warning(
                "Telegram API вернул %d при отправке уведомления: %s",
                resp.status_code, resp.text[:200],
            )
    except Exception as exc:
        logger.error("Ошибка отправки Telegram-уведомления: %s", exc)


@shared_task(
    bind=True,
    autoretry_for=(RequestError, ConnectionError),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=5,
)
def sync_user_portfolio(self, user_id: int):
    """
    Синхронизирует счета и портфель ОДНОГО конкретного пользователя.
    Изолирована: сбой у этого инвестора не сломает синхронизацию остальных.
    """
    user = InvestorUser.objects.filter(id=user_id).first()
    if not user:
        logger.warning(f"Пользователь #{user_id} не найден в базе данных.")
        return

    # Получаем активные токены пользователя
    tokens_to_sync = list(user.broker_tokens.filter(is_active=True))
    if not tokens_to_sync and user.encrypted_token:
        # Fallback для совместимости
        tokens_to_sync = [user]

    if not tokens_to_sync:
        logger.warning(f"У пользователя #{user_id} отсутствует активный токен Т-Банка.")
        return

    for token_obj in tokens_to_sync:
        token = token_obj.decrypted_token
        if not token:
            continue

        broker_token = token_obj if hasattr(token_obj, "user_id") else None

        try:
            with Client(token) as client:
                accounts_response = client.users.get_accounts()

                for acc in accounts_response.accounts:
                    account, _ = Account.objects.update_or_create(
                        account_id=acc.id,
                        defaults={
                            "investor": user,
                            "broker_token": broker_token,
                            "name": acc.name,
                            "account_type": str(acc.type),
                            "status": str(acc.status),
                        },
                    )

                    # Если у пользователя еще не выбран активный счет — ставим этот
                    if not user.active_account:
                        user.active_account = account
                        user.save(update_fields=["active_account"])

                    portfolio = client.operations.get_portfolio(account_id=acc.id)
                    snapshot = save_portfolio_snapshot(
                        account=account,
                        portfolio_data=portfolio,
                        client=client,
                    )
                    logger.info(
                        f"✅ Снимок #{snapshot.id} сохранен для счета '{acc.name}' "
                        f"(инвестор #{user.id}, баланс: {snapshot.total_amount_portfolio} руб.)"
                    )

                    cache.delete(f"chart:account:{account.id}")
                    cache.delete(f"chart:consolidated:{user.id}")

        except RequestError as exc:
            if "UNAUTHENTICATED" in str(exc) or "401" in str(exc):
                logger.error(
                    "❌ Токен %s пользователя #%d недействителен: %s",
                    token_obj, user.id, exc,
                )
                _deactivate_token_and_notify(token_obj, user)
                continue
            raise



@shared_task
def sync_portfolios():
    """
    Диспетчер для Celery Beat.
    Раз в час находит всех пользователей с токенами и ставит каждому отдельную задачу.
    """
    # values_list возвращает int, а не объект — баг исправлен: user.id → user
    user_ids = (
        InvestorUser.objects
        .exclude(encrypted_token="")
        .values_list("id", flat=True)
        .iterator(chunk_size=2000)
    )
    count = 0
    for user_id in user_ids:
        sync_user_portfolio.delay(user_id)
        count += 1

    logger.info(f"📢 Диспетчер запланировал синхронизацию для {count} инвесторов.")


@shared_task
def downsample_snapshots():
    """
    Прореживание истории снимков (Downsampling / Rollup).
    Запускается раз в сутки в 02:00 по расписанию Celery Beat.

    Политика хранения:
      0–7 дней   → оставляем все снимки (детальная история).
      7–90 дней  → 1 снимок в сутки (последний за день).
      90–365 дней → 1 снимок в неделю (последний в воскресенье или ближайший).
      > 365 дней → удаляем все.
    """
    now = timezone.now()
    boundary_7d = now - timezone.timedelta(days=7)
    boundary_90d = now - timezone.timedelta(days=90)
    boundary_365d = now - timezone.timedelta(days=365)

    total_deleted = 0
    accounts = Account.objects.all().values_list("id", flat=True)

    for account_id in accounts:
        with transaction.atomic():
            # ── Зона 3: старше 365 дней — удалить всё ────────────────────────
            deleted_old, _ = (
                PortfolioSnapshot.objects
                .filter(account_id=account_id, created_at__lt=boundary_365d)
                .delete()
            )
            total_deleted += deleted_old

            # ── Зона 2: 90–365 дней — 1 снимок в неделю ─────────────────────
            snapshots_90_365 = list(
                PortfolioSnapshot.objects
                .filter(
                    account_id=account_id,
                    created_at__gte=boundary_365d,
                    created_at__lt=boundary_90d,
                )
                .order_by("created_at")
                .values_list("id", "created_at")
            )
            keep_ids = _pick_weekly(snapshots_90_365)
            deleted_w, _ = (
                PortfolioSnapshot.objects
                .filter(account_id=account_id)
                .filter(
                    created_at__gte=boundary_365d,
                    created_at__lt=boundary_90d,
                )
                .exclude(id__in=keep_ids)
                .delete()
            )
            total_deleted += deleted_w

            # ── Зона 1: 7–90 дней — 1 снимок в сутки ────────────────────────
            snapshots_7_90 = list(
                PortfolioSnapshot.objects
                .filter(
                    account_id=account_id,
                    created_at__gte=boundary_90d,
                    created_at__lt=boundary_7d,
                )
                .order_by("created_at")
                .values_list("id", "created_at")
            )
            keep_ids_daily = _pick_daily(snapshots_7_90)
            deleted_d, _ = (
                PortfolioSnapshot.objects
                .filter(account_id=account_id)
                .filter(
                    created_at__gte=boundary_90d,
                    created_at__lt=boundary_7d,
                )
                .exclude(id__in=keep_ids_daily)
                .delete()
            )
            total_deleted += deleted_d

    logger.info(
        f"📊 Downsampling завершён: удалено {total_deleted} устаревших снимков "
        f"для {len(list(accounts))} счетов."
    )
    return total_deleted


# ── Вспомогательные функции прореживания ────────────────────────────────────

def _pick_daily(snapshots: list[tuple]) -> list[int]:
    """
    Из списка (id, created_at) выбирает один снимок на каждые сутки —
    самый поздний за день (ближе к 23:59).
    Возвращает список id, которые надо ОСТАВИТЬ.
    """
    best: dict[tuple, tuple[int, object]] = {}
    for snap_id, created_at in snapshots:
        day_key = (created_at.year, created_at.month, created_at.day)
        if day_key not in best or created_at > best[day_key][1]:
            best[day_key] = (snap_id, created_at)
    return [v[0] for v in best.values()]


def _pick_weekly(snapshots: list[tuple]) -> list[int]:
    """
    Из списка (id, created_at) выбирает один снимок на каждую ISO-неделю —
    самый поздний за неделю.
    Возвращает список id, которые надо ОСТАВИТЬ.
    """
    best: dict[tuple, tuple[int, object]] = {}
    for snap_id, created_at in snapshots:
        iso_cal = created_at.isocalendar()
        week_key = (iso_cal[0], iso_cal[1])  # (iso_year, iso_week)
        if week_key not in best or created_at > best[week_key][1]:
            best[week_key] = (snap_id, created_at)
    return [v[0] for v in best.values()]
