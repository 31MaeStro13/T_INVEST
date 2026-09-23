"""
Фоновые задачи Celery для пакетного пересчёта рисков с чанкингом.
"""

import logging
from celery import shared_task
import numpy as np
from django.core.cache import cache

from users.models import InvestorUser
from portfolio.models import Account, PortfolioSnapshot
from .batch import compute_batch_metrics

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
