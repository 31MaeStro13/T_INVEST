"""
Django-слой аналитики: достаём данные из БД и вызываем NumPy-движок.
"""

from __future__ import annotations

from portfolio.models import Account, PortfolioSnapshot
from . import engine
from django.core.cache import cache
from .charts import generate_portfolio_dashboard


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

def get_chart_for_account(account_id: int) -> bytes | None:
    """
    Генерирует PNG-дашборд для конкретного брокерского счета с кэшированием в Redis.
    """
    cache_key = f"chart:account:{account_id}"
    cached_chart = cache.get(cache_key)
    if cached_chart:
        return cached_chart
    try:
        account = Account.objects.get(pk=account_id)
    except Account.DoesNotExist:
        return None
    # Достаем хронологию (только даты и балансы)
    snapshots = (
        account.snapshots
        .order_by("created_at")
        .values_list("created_at", "total_amount_portfolio")
    )
    dates = [s[0] for s in snapshots]
    values = [float(s[1]) for s in snapshots]
    # Доли активов из последнего снимка
    latest = account.snapshots.order_by("-created_at").first()
    assets = {
        "shares_amount": float(latest.total_amount_shares) if latest else 0.0,
        "bonds_amount": float(latest.total_amount_bonds) if latest else 0.0,
        "etf_amount": float(latest.total_amount_etf) if latest else 0.0,
        "currencies_amount": float(latest.total_amount_currencies) if latest else 0.0,
    }
    chart_bytes = generate_portfolio_dashboard(
        dates=dates,
        values=values,
        assets=assets,
        account_name=account.name,
    )
    # Кэшируем результат в Redis на 10 минут
    cache.set(cache_key, chart_bytes, timeout=600)
    return chart_bytes


def get_consolidated_chart(user) -> bytes | None:
    """
    Генерирует сводный PNG-дашборд по всем счетам пользователя с кэшированием в Redis.
    """
    cache_key = f"chart:consolidated:{user.id}"
    cached_chart = cache.get(cache_key)
    if cached_chart:
        return cached_chart
    from portfolio.services import get_consolidated_snapshot
    # Текущие доли по всем счетам
    consolidated_snap = get_consolidated_snapshot(user)
    if not consolidated_snap:
        return None
    assets = {
        "shares_amount": float(consolidated_snap.get("total_amount_shares") or 0.0),
        "bonds_amount": float(consolidated_snap.get("total_amount_bonds") or 0.0),
        "etf_amount": float(consolidated_snap.get("total_amount_etf") or 0.0),
        "currencies_amount": float(consolidated_snap.get("total_amount_currencies") or 0.0),
    }
    # Для сводной динамики берем снимки всех активных счетов
    active_token = user.broker_tokens.filter(is_active=True).first()
    accounts = user.accounts.filter(broker_token=active_token) if active_token else user.accounts.all()
    snapshots = (
        PortfolioSnapshot.objects
        .filter(account__in=accounts)
        .order_by("created_at")
        .values_list("created_at", "total_amount_portfolio")
    )
    dates = [s[0] for s in snapshots]
    values = [float(s[1]) for s in snapshots]
    chart_bytes = generate_portfolio_dashboard(
        dates=dates,
        values=values,
        assets=assets,
        account_name="Все счета банка",
    )
    cache.set(cache_key, chart_bytes, timeout=600)
    return chart_bytes
