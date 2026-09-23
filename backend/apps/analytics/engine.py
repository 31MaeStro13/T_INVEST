"""
Аналитическое NumPy-ядро портфельного аудитора.

Все функции принимают plain Python списки/float и возвращают dict —
чтобы не тащить зависимость от NumPy в Django views и тесты можно
запускать без БД.

Соглашения:
- equity   : list[float] — исторический вектор стоимости портфеля по снимкам
- returns  : np.ndarray  — вектор дневных лог-доходностей
- TRADING_DAYS_YEAR = 252 (стандарт MOEX и мировых бирж)
"""

from __future__ import annotations

import numpy as np

TRADING_DAYS_YEAR = 252
MIN_PERIODS = 3  # Минимум снимков для расчёта метрик


def _log_returns(equity: np.ndarray) -> np.ndarray:
    """Вектор логарифмических доходностей из ценового ряда."""
    # Защита: убираем нули и отрицательные значения (некорректные данные)
    equity = np.where(equity <= 0, np.nan, equity)
    return np.diff(np.log(equity))


def max_drawdown(equity: list[float]) -> float:
    """
    Максимальная историческая просадка (Max Drawdown).

    Показывает наибольшее падение от пика до дна за весь наблюдаемый период.
    Результат в долях (например, -0.25 = -25%).

    Алгоритм: для каждого момента времени считаем отклонение текущей стоимости
    от бегущего максимума (кумулятивного пика). Берём минимум по всей истории.
    """
    arr = np.array(equity, dtype=np.float64)
    if len(arr) < MIN_PERIODS:
        return 0.0

    # Кумулятивный пик (бегущий максимум)
    peak = np.maximum.accumulate(arr)
    # Просадка в каждый момент: (текущее - пик) / пик
    drawdowns = np.where(peak > 0, (arr - peak) / peak, 0.0)
    return float(drawdowns.min())


def annual_volatility(equity: list[float]) -> float:
    """
    Годовая волатильность (аннуализированное стандартное отклонение доходностей).

    Показывает «нервозность» портфеля: насколько сильно он скачет.
    Результат в долях (например, 0.15 = 15% годовых).

    Формула: std(log_returns) * sqrt(252)
    """
    arr = np.array(equity, dtype=np.float64)
    if len(arr) < MIN_PERIODS:
        return 0.0

    r = _log_returns(arr)
    r = r[~np.isnan(r)]  # убираем NaN после замены нулей

    if len(r) < 2:
        return 0.0

    daily_std = float(np.std(r, ddof=1))
    return float(daily_std * np.sqrt(TRADING_DAYS_YEAR))


def sharpe_ratio(equity: list[float], risk_free_rate: float = 0.19) -> float:
    """
    Коэффициент Шарпа.

    Показывает, оправдан ли принятый риск: сколько единиц доходности
    сверх безрисковой ставки приходится на единицу волатильности.

    Интерпретация:
      < 0    — хуже депозита
      0–1    — риск не окупается
      1–2    — нормально
      > 2    — отлично (уровень алго-фондов)

    risk_free_rate: ключевая ставка ЦБ РФ (по умолчанию 19% = 0.19).
    """
    arr = np.array(equity, dtype=np.float64)
    if len(arr) < MIN_PERIODS:
        return 0.0

    r = _log_returns(arr)
    r = r[~np.isnan(r)]

    if len(r) < 2:
        return 0.0

    # Аннуализированная доходность через среднее лог-доходностей * 252
    mean_annual_return = float(np.mean(r) * TRADING_DAYS_YEAR)
    vol = float(np.std(r, ddof=1) * np.sqrt(TRADING_DAYS_YEAR))

    if vol == 0.0:
        return 0.0

    return float((mean_annual_return - risk_free_rate) / vol)


def sector_allocation(positions: list[dict]) -> dict[str, float]:
    """
    Секторная разбивка портфеля по классам инструментов.

    Принимает список позиций (из PortfolioSnapshotSerializer).
    Возвращает словарь {тип: доля_в_портфеле} в долях от 1.

    Пример: {"share": 0.45, "bond": 0.30, "etf": 0.25}
    """
    totals: dict[str, float] = {}
    grand_total = 0.0

    for pos in positions:
        try:
            qty = float(pos.get("quantity") or 0)
            price = float(pos.get("current_price") or 0)
            value = qty * price
            itype = str(pos.get("instrument_type") or "other").lower()
            totals[itype] = totals.get(itype, 0.0) + value
            grand_total += value
        except (TypeError, ValueError):
            continue

    if grand_total == 0.0:
        return {}

    return {k: round(v / grand_total, 4) for k, v in totals.items()}


def concentration_risk(positions: list[dict]) -> list[dict]:
    """
    Анализ концентрации: какие эмитенты занимают критическую долю (>25%).

    Возвращает список позиций с превышением порога — отсортированный
    по убыванию доли. Каждый элемент содержит:
      ticker, name, value, ratio, is_critical (>25%)
    """
    items = []
    grand_total = 0.0

    for pos in positions:
        try:
            qty = float(pos.get("quantity") or 0)
            price = float(pos.get("current_price") or 0)
            value = qty * price
            grand_total += value
            items.append({
                "ticker": pos.get("ticker") or pos.get("figi", ""),
                "name": pos.get("name", ""),
                "value": value,
            })
        except (TypeError, ValueError):
            continue

    if grand_total == 0.0:
        return []

    result = []
    for item in items:
        ratio = item["value"] / grand_total
        result.append({
            "ticker": item["ticker"],
            "name": item["name"],
            "value": round(item["value"], 2),
            "ratio": round(ratio, 4),
            "is_critical": ratio > 0.25,
        })

    return sorted(result, key=lambda x: x["ratio"], reverse=True)


def compute_all(equity: list[float], positions: list[dict], risk_free_rate: float = 0.19) -> dict:
    """
    Агрегированный расчёт всех метрик портфеля за один вызов.

    Возвращает готовый dict для сериализации в DRF Response.
    """
    mdd = max_drawdown(equity)
    vol = annual_volatility(equity)
    sharpe = sharpe_ratio(equity, risk_free_rate)
    allocation = sector_allocation(positions)
    concentration = concentration_risk(positions)

    # Уровень риска по волатильности
    if vol == 0.0:
        risk_level = "Нет данных"
    elif vol < 0.10:
        risk_level = "Низкий"
    elif vol < 0.20:
        risk_level = "Умеренный"
    elif vol < 0.35:
        risk_level = "Высокий"
    else:
        risk_level = "Экстремальный"

    return {
        "snapshots_count": len(equity),
        "max_drawdown": round(mdd * 100, 2),          # в процентах
        "annual_volatility": round(vol * 100, 2),      # в процентах
        "sharpe_ratio": round(sharpe, 3),
        "risk_free_rate": round(risk_free_rate * 100, 1),
        "risk_level": risk_level,
        "sector_allocation": allocation,
        "concentration_risk": concentration,
        "has_sufficient_data": len(equity) >= MIN_PERIODS,
    }
