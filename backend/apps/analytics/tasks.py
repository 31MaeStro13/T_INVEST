import logging
import os
import json
import urllib.request
from celery import shared_task
import numpy as np
from django.core.cache import cache

from users.models import InvestorUser
from portfolio.models import Account, PortfolioSnapshot
from .batch import compute_batch_metrics
from .alerts import evaluate_risk_triggers
from .service import get_consolidated_analytics

logger = logging.getLogger(__name__)


@shared_task(name="analytics.process_risk_chunk")
def process_risk_chunk(user_ids: list[int]) -> dict[str, int]:
    """
    Обработка одного чанка пользователей в отдельном процессе Celery воркера.
    Формирует 2D-матрицу капитала и рассчитывает метрики векторно.
    """
    if not user_ids:
        return {"processed": 0}

    # 1. Извлекаем последние N снимков для каждого пользователя плоским запросом
    # Избегаем тяжелых моделей Django ORM ради экономии памяти (C-contiguous RAM)
    histories: list[list[float]] = []
    valid_user_ids: list[int] = []

    for uid in user_ids:
        account_ids = Account.objects.filter(investor_id=uid).values_list("id", flat=True)
        if not account_ids:
            continue

        # Собираем исторические суммы снимков
        snaps = (
            PortfolioSnapshot.objects
            .filter(account_id__in=account_ids)
            .order_by("created_at")
            .values_list("total_amount_portfolio", flat=True)
        )
        vals = [float(v) for v in snaps if v > 0]
        if len(vals) >= 3:
            histories.append(vals)
            valid_user_ids.append(uid)

    if not histories:
        return {"processed": 0}

    # 2. Выравнивание длины рядов для 2D-матрицы
    min_len = min(len(h) for h in histories)
    aligned_matrix = np.array([h[-min_len:] for h in histories], dtype=np.float64)

    # 3. Векторный расчёт по 2D матрице за 1 вызов (SIMD/NEON)
    results = compute_batch_metrics(aligned_matrix)

    # 4. Сохраняем результаты в Redis-кэш (быстрый доступ для бота)
    for idx, uid in enumerate(valid_user_ids):
        cache_key = f"user_risk_metrics:{uid}"
        data = {
            "volatility": float(results["annual_volatilities"][idx]),
            "max_drawdown": float(results["max_drawdowns"][idx]),
            "sharpe": float(results["sharpe_ratios"][idx]),
        }
        cache.set(cache_key, data, timeout=86400)

    logger.info(f"Успешно обработан чанк из {len(valid_user_ids)} инвесторов через 2D NumPy матрицу.")
    return {"processed": len(valid_user_ids)}


@shared_task(name="analytics.nightly_batch_risk_audit")
def nightly_batch_risk_audit(chunk_size: int = 100) -> dict[str, int]:
    """
    Ночной запуск аудита по всей базе пользователей с нарезкой на чанки.
    Распараллеливается по пулу процессов воркеров Celery.
    """
    user_ids = list(InvestorUser.objects.values_list("id", flat=True))
    total_users = len(user_ids)
    
    if not total_users:
        return {"total_users": 0, "chunks_dispatched": 0}

    # Нарезка на чанки
    chunks = [user_ids[i : i + chunk_size] for i in range(0, total_users, chunk_size)]
    for chunk in chunks:
        process_risk_chunk.delay(chunk)

    logger.info(f"Ночной аудит: запущено {len(chunks)} чанков для {total_users} пользователей.")
    return {"total_users": total_users, "chunks_dispatched": len(chunks)}


@shared_task(name="analytics.check_and_send_risk_alerts")
def check_and_send_risk_alerts(target_telegram_id: int | None = None) -> dict[str, int]:
    """
    Периодическая задача Celery: аудит рисков и отправка Smart Alerts в Telegram.
    Проверяет:
      1. Концентрацию активов (>25%)
      2. Превышение порога просадки (mDD <= -5%)
      3. Отрицательный Шарп при повышенной волатильности
    Дедупликация: не чаще одного алерта по конкретному риску в 24 часа через Redis.
    """
    users_query = InvestorUser.objects.filter(alerts_enabled=True)
    if target_telegram_id:
        users_query = users_query.filter(telegram_id=target_telegram_id)

    users = list(users_query)
    bot_token = os.getenv("BOT_TOKEN", "")
    if not bot_token:
        logger.warning("BOT_TOKEN не задан, отправка алертов невозможна.")
        return {"sent": 0, "skipped": 0}

    sent_count = 0
    skipped_count = 0

    for user in users:
        if not user.accounts.exists():
            continue

        analytics = get_consolidated_analytics(user)
        if not analytics:
            continue

        alerts = evaluate_risk_triggers(analytics)
        if not alerts:
            continue

        for alert in alerts:
            alert_type = alert.get("type", "general")
            item_key = alert.get("item_key", "default")
            dedup_key = f"alert_sent:{user.id}:{alert_type}:{item_key}"

            # Проверка дедупликации в Redis (24 часа)
            if cache.get(dedup_key):
                skipped_count += 1
                continue

            text = (
                f"🔔 <b>Мониторинг рисков: {analytics.get('account_name', 'Все счета')}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"<b>{alert['title']}</b>\n"
                f"{alert['message']}\n\n"
                "⚖️ <i>Предоставленная информация носит исключительно ознакомительный и аналитический характер "
                "и не является индивидуальной инвестиционной рекомендацией (ст. 6.1 39-ФЗ).</i>"
            )

            try:
                url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                payload = json.dumps({
                    "chat_id": user.telegram_id,
                    "text": text,
                    "parse_mode": "HTML",
                }).encode("utf-8")

                req = urllib.request.Request(
                    url,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    if resp.status == 200:
                        sent_count += 1
                        cache.set(dedup_key, 1, timeout=86400)
                        logger.info(f"Алерт '{alert_type}' успешно отправлен пользователю #{user.telegram_id}")
            except Exception as e:
                logger.error(f"Сбой отправки алерта пользователю #{user.telegram_id}: {e}")

    return {"sent": sent_count, "skipped": skipped_count}
