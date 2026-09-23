from decimal import Decimal
from django.db import transaction

from .models import Account, PortfolioSnapshot, Position
from t_tech.invest.utils import money_to_decimal, quotation_to_decimal
from users.models import InvestorUser

_INSTRUMENT_CACHE: dict[str, tuple[str, str]] = {
    "RUB000UTSTOM": ("Рубль РФ (Кэш)", "RUB"),
}


def resolve_instrument(client, figi: str, fallback_ticker: str = "") -> tuple[str, str]:
    """Разрешает название и тикер инструмента по FIGI с кэшированием."""
    if not figi:
        return "", fallback_ticker
    if figi in _INSTRUMENT_CACHE:
        return _INSTRUMENT_CACHE[figi]
    if client:
        try:
            from t_tech.invest import InstrumentIdType
            res = client.instruments.get_instrument_by(
                id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_FIGI, id=figi
            )
            name = res.instrument.name or ""
            ticker = res.instrument.ticker or fallback_ticker
            _INSTRUMENT_CACHE[figi] = (name, ticker)
            return name, ticker
        except Exception:
            pass
    return "", fallback_ticker


def save_portfolio_snapshot(account: Account, portfolio_data, client=None) -> PortfolioSnapshot:
    with transaction.atomic():
        portfoliosnapshot = PortfolioSnapshot.objects.create(
            account=account,
            total_amount_portfolio=money_to_decimal(portfolio_data.total_amount_portfolio),
            total_amount_shares=money_to_decimal(portfolio_data.total_amount_shares),
            total_amount_bonds=money_to_decimal(portfolio_data.total_amount_bonds),
            total_amount_etf=money_to_decimal(portfolio_data.total_amount_etf),
            total_amount_currencies=money_to_decimal(portfolio_data.total_amount_currencies),
            expected_yield=quotation_to_decimal(portfolio_data.expected_yield) if portfolio_data.expected_yield else Decimal("0"),
        )
        position_to_create = []

        for pos in portfolio_data.positions:
            pos_ticker = getattr(pos, "ticker", "") or ""
            name, ticker = resolve_instrument(client, pos.figi, fallback_ticker=pos_ticker)
            position_to_create.append(
                Position(
                    snapshot=portfoliosnapshot,
                    figi=pos.figi,
                    ticker=ticker,
                    name=name,
                    instrument_type=pos.instrument_type,
                    quantity=quotation_to_decimal(pos.quantity),
                    current_price=money_to_decimal(pos.current_price),
                    average_position_price=money_to_decimal(pos.average_position_price),
                    expected_yield=quotation_to_decimal(pos.expected_yield) if pos.expected_yield else Decimal("0"),
                )
            )

        Position.objects.bulk_create(position_to_create)
        return portfoliosnapshot

from users.models import InvestorUser
from .models import Account


def get_consolidated_snapshot(user: InvestorUser, broker_token=None) -> dict | None:
    # 1. Находим все счета пользователя (для активного токена)
    accounts = Account.objects.filter(investor=user)
    if broker_token:
        accounts = accounts.filter(broker_token=broker_token)
    elif user.active_broker_token:
        accounts = accounts.filter(broker_token=user.active_broker_token)

    # 2. Достаем последний снимок для каждого счета
    snapshots = []
    for acc in accounts:
        latest = acc.snapshots.prefetch_related("positions").order_by("-created_at").first()
        if latest:
            snapshots.append(latest)

    if not snapshots:
        return None

    # 3. Суммируем общие балансы портфеля
    total_portfolio = sum((s.total_amount_portfolio for s in snapshots), Decimal("0"))
    total_shares = sum((s.total_amount_shares for s in snapshots), Decimal("0"))
    total_bonds = sum((s.total_amount_bonds for s in snapshots), Decimal("0"))
    total_etf = sum((s.total_amount_etf for s in snapshots), Decimal("0"))
    total_currencies = sum((s.total_amount_currencies for s in snapshots), Decimal("0"))
    total_yield = sum((s.expected_yield for s in snapshots), Decimal("0"))

    # 4. Склеиваем позиции по всем счетам (по FIGI)
    positions_map: dict[str, dict] = {}
    for s in snapshots:
        for p in s.positions.all():
            key = p.figi or p.ticker or str(p.id)
            qty = p.quantity or Decimal("0")
            price = p.current_price or Decimal("0")
            pnl = p.expected_yield or Decimal("0")

            if key not in positions_map:
                positions_map[key] = {
                    "figi": p.figi,
                    "ticker": p.ticker or "",
                    "name": p.name or p.ticker or "Ценная бумага",
                    "instrument_type": p.instrument_type or "share",
                    "quantity": qty,
                    "current_price": price,
                    "expected_yield": pnl,
                }
            else:
                # Если бумага уже есть на другом счете — суммируем количество и прибыль
                positions_map[key]["quantity"] += qty
                positions_map[key]["expected_yield"] += pnl
                # Если названия не было в первом снимке, берем из текущего
                if not positions_map[key]["name"] and p.name:
                    positions_map[key]["name"] = p.name

    # Подтягиваем известные имена из БД для позиций, где имя еще не было сохранено
    missing_names = [
        k for k, v in positions_map.items()
        if not v["name"] or v["name"] in ("Ценная бумага", v["figi"], "")
    ]
    if missing_names:
        known = dict(
            Position.objects
            .filter(figi__in=missing_names)
            .exclude(name="")
            .exclude(name="Неизвестный инструмент")
            .exclude(name="Ценная бумага")
            .values_list("figi", "name")
        )
        known_tickers = dict(
            Position.objects
            .filter(figi__in=missing_names)
            .exclude(ticker="")
            .values_list("figi", "ticker")
        )
        for figi, known_name in known.items():
            if figi in positions_map:
                positions_map[figi]["name"] = known_name
        for figi, known_t in known_tickers.items():
            if figi in positions_map and not positions_map[figi]["ticker"]:
                positions_map[figi]["ticker"] = known_t

    # 5. Приводим позиции к списку и форматируем числа в строки для JSON
    consolidated_positions = []
    for pos in positions_map.values():
        consolidated_positions.append({
            "figi": pos["figi"],
            "ticker": pos["ticker"],
            "name": pos["name"],
            "instrument_type": pos["instrument_type"],
            "quantity": str(pos["quantity"]),
            "current_price": str(pos["current_price"]),
            "expected_yield": str(pos["expected_yield"]),
        })

    # Сортируем: сначала самые крупные активы
    consolidated_positions.sort(
        key=lambda x: float(x["quantity"]) * float(x["current_price"]),
        reverse=True,
    )

    # 6. Возвращаем единый агрегированный снимок
    latest_date = max((s.created_at for s in snapshots), default=None)
    return {
        "id": "consolidated",
        "account_name": "Все счета Т-Банка",
        "created_at": latest_date.isoformat() if latest_date else "",
        "total_amount_portfolio": str(total_portfolio),
        "total_amount_shares": str(total_shares),
        "total_amount_bonds": str(total_bonds),
        "total_amount_etf": str(total_etf),
        "total_amount_currencies": str(total_currencies),
        "expected_yield": str(total_yield),
        "positions": consolidated_positions,
    }
