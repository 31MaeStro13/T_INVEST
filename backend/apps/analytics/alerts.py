"""
Модуль проверки риск-триггеров портфеля для системы Smart Alerts.
"""
from typing import Any


def evaluate_risk_triggers(analytics_data: dict[str, Any]) -> list[dict[str, str]]:
    """
    Проверяет метрики портфеля на превышение порогов риска.
    Возвращает список обнаруженных алертов с ключами для дедупликации в Redis.
    """
    alerts: list[dict[str, str]] = []
    if not analytics_data:
        return alerts

    # 1. Проверка риска концентрации (>25% на один актив)
    concentration = analytics_data.get("concentration_risk", [])
    for pos in concentration:
        if pos.get("is_critical", False) or float(pos.get("ratio") or 0.0) >= 0.25:
            ticker = pos.get("ticker") or "Актив"
            name = pos.get("name")
            name_str = f" ({name})" if name else ""
            ratio = round(float(pos.get("ratio") or 0.0) * 100, 1)

            alerts.append({
                "type": "concentration",
                "item_key": ticker,
                "title": "⚠️ Высокая концентрация капитала",
                "message": (
                    f"Актив <b>{ticker}</b>{name_str} занимает <b>{ratio}%</b> вашего совокупного портфеля "
                    f"(выше рекомендуемого лимита 25%). Сильные колебания этой бумаги могут оказать "
                    "критическое влияние на весь капитал."
                ),
            })

    # 2. Проверка глубокой просадки (mDD <= -5.0%)
    mdd = float(analytics_data.get("max_drawdown") or 0.0)
    if mdd <= -5.0:
        alerts.append({
            "type": "drawdown",
            "item_key": "mdd",
            "title": "📉 Превышен порог просадки",
            "message": (
                f"Текущая просадка портфеля от локального пика достигла <b>{mdd:.2f}%</b>. "
                "Рекомендуем проверить структуру активов и защитные инструменты."
            ),
        })

    # 3. Проверка неэффективного риска (Шарп < 0 при высокой волатильности)
    vol = float(analytics_data.get("annual_volatility") or 0.0)
    sharpe = float(analytics_data.get("sharpe_ratio") or 0.0)
    has_history = analytics_data.get("has_sufficient_data", True)

    if has_history and vol > 15.0 and sharpe < 0.0:
        alerts.append({
            "type": "sharpe_warning",
            "item_key": "sharpe",
            "title": "🧮 Неоправданный риск портфеля",
            "message": (
                f"Годовая волатильность повышена (<b>{vol:.1f}%</b>), а коэффициент Шарпа "
                f"отрицательный (<code>{sharpe:.2f}</code>). Доходность портфеля пока уступает "
                "безрисковой доходности депозитов или ОФЗ под 19%."
            ),
        })

    return alerts
