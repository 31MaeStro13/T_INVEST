"""
Django-слой аналитики: достаём данные из БД и вызываем NumPy-движок.
"""

from __future__ import annotations

from portfolio.models import Account, PortfolioSnapshot
from . import engine


def get_analytics_for_account(account_id: int, days: int = 90, risk_free_rate: float = 0.19) -> dict | None:
    """
    Основная точка входа: возвращает полный аналитический отчёт по счёту.

    account_id : PK счёта в нашей БД (не account_id Т-Банка!)
    days       : глубина истории в днях (по умолчанию 90)
    risk_free_rate : безрисковая ставка (ключевая ставка ЦБ, по умолчанию 19%)

    Возвращает None если счёт не найден.
    """
    try:
        account = Account.objects.get(pk=account_id)
    except Account.DoesNotExist:
        return None

    # Достаём снимки за период, сортированные хронологически
    snapshots = (
        account.snapshots
        .order_by("created_at")
        .values("total_amount_portfolio")
    )

    # Вектор стоимости портфеля во времени (float)
    equity = [float(s["total_amount_portfolio"]) for s in snapshots]

    # Последние позиции из самого свежего снимка
    latest = account.snapshots.prefetch_related("positions").order_by("-created_at").first()
    positions = []
    if latest:
        positions = list(
            latest.positions.values("ticker", "name", "figi", "instrument_type", "quantity", "current_price")
        )
        # Приводим Decimal к float для NumPy
        for p in positions:
            p["quantity"] = float(p.get("quantity") or 0)
            p["current_price"] = float(p.get("current_price") or 0)

    result = engine.compute_all(equity, positions, risk_free_rate)
    result["account_id"] = account_id
    result["account_name"] = account.name

    return result


def get_consolidated_analytics(user, days: int = 90, risk_free_rate: float = 0.19) -> dict | None:
    """
    Возвращает консолидированный аналитический отчёт по всем счетам пользователя (для активного токена).
    """
    from portfolio.services import get_consolidated_snapshot
    from portfolio.models import Account, PortfolioSnapshot

    accounts = Account.objects.filter(investor=user)
    if user.active_broker_token:
        accounts = accounts.filter(broker_token=user.active_broker_token)

    if not accounts.exists():
        return None

    consolidated_snap = get_consolidated_snapshot(user)
    if not consolidated_snap:
        return None

    positions = []
    for p in consolidated_snap.get("positions", []):
        positions.append({
            "ticker": p.get("ticker", ""),
            "name": p.get("name", ""),
            "figi": p.get("figi", ""),
            "instrument_type": p.get("instrument_type", ""),
            "quantity": float(p.get("quantity") or 0),
            "current_price": float(p.get("current_price") or 0),
        })

    account_ids = list(accounts.values_list("id", flat=True))
    first_dates = [
        PortfolioSnapshot.objects.filter(account_id=aid).order_by("created_at").values_list("created_at", flat=True).first()
        for aid in account_ids
    ]
    first_dates = [d for d in first_dates if d]

    equity = []
    if first_dates:
        start_date = max(first_dates)
        from django.db.models.functions import TruncMinute
        minutes = (
            PortfolioSnapshot.objects
            .filter(account_id__in=account_ids, created_at__gte=start_date)
            .annotate(minute=TruncMinute("created_at"))
            .values_list("minute", flat=True)
            .distinct()
            .order_by("minute")
        )
        for m in minutes:
            tot = sum(
                PortfolioSnapshot.objects
                .filter(account_id=aid, created_at__lte=m.replace(second=59, microsecond=999999))
                .order_by("-created_at")
                .values_list("total_amount_portfolio", flat=True)
                .first() or 0
                for aid in account_ids
            )
            if tot > 0:
                equity.append(float(tot))

    if not equity:
        total_val = float(consolidated_snap.get("total_amount_portfolio") or 0)
        equity = [total_val]

    result = engine.compute_all(equity, positions, risk_free_rate)
    result["account_id"] = "consolidated"
    result["account_name"] = "Все счета Т-Банка (Консолидировано)"

    return result

