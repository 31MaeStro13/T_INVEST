from decimal import Decimal
from typing import Any


def format_currency(val: Any) -> str:
    """Форматирует сумму в финансовый вид: 1 250 400.00 ₽"""
    if val is None:
        return "0.00 ₽"
    try:
        num = float(val)
        formatted = f"{num:,.2f}".replace(",", " ")
        return f"{formatted} ₽"
    except (ValueError, TypeError):
        return f"{val} ₽"


def format_yield(val: Any) -> str:
    """Форматирует доходность с цветовым маркером."""
    if val is None:
        return "⚪️ 0.00 ₽"
    try:
        num = float(val)
        formatted = f"{abs(num):,.2f}".replace(",", " ")
        if num > 0:
            return f"🟢 +{formatted} ₽"
        elif num < 0:
            return f"🔴 -{formatted} ₽"
        else:
            return f"⚪️ 0.00 ₽"
    except (ValueError, TypeError):
        return f"{val} ₽"


def format_progress_bar(part: float, total: float, width: int = 10) -> str:
    """Генерирует аккуратный визуальный прогресс-бар: [██████░░░░] 60.0%"""
    if total <= 0:
        return f"[{'░' * width}] 0.0%"
    pct = max(0.0, min(100.0, (part / total) * 100.0))
    filled = int(round((pct / 100.0) * width))
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {pct:.1f}%"


def build_portfolio_text(account: dict, snapshot: dict) -> str:
    """Формирует структурированный дашборд портфеля."""
    acc_name = account.get("name", "Основной счет")
    created_at = snapshot.get("created_at", "")[:19].replace("T", " ")

    total = float(snapshot.get("total_amount_portfolio") or 0)
    shares = float(snapshot.get("total_amount_shares") or 0)
    bonds = float(snapshot.get("total_amount_bonds") or 0)
    etf = float(snapshot.get("total_amount_etf") or 0)
    currencies = float(snapshot.get("total_amount_currencies") or 0)
    expected_yield = snapshot.get("expected_yield") or 0
    positions = snapshot.get("positions", [])

    lines = [
        f"💼 <b>Счет:</b> {acc_name}",
        f"📅 <b>Снимок от:</b> {created_at}",
        "━━━━━━━━━━━━━━━━━━━━",
        f"💰 <b>Общий баланс:</b> <code>{format_currency(total)}</code>",
        f"🎯 <b>Доходность:</b> {format_yield(expected_yield)}",
        "━━━━━━━━━━━━━━━━━━━━",
        "<b>📊 Структура активов:</b>",
        f"• Акции: <b>{format_currency(shares)}</b> {format_progress_bar(shares, total)}",
        f"• Облигации: <b>{format_currency(bonds)}</b> {format_progress_bar(bonds, total)}",
        f"• Фонды (ETF): <b>{format_currency(etf)}</b> {format_progress_bar(etf, total)}",
        f"• Валюта / Кэш: <b>{format_currency(currencies)}</b> {format_progress_bar(currencies, total)}",
        "━━━━━━━━━━━━━━━━━━━━",
        f"📦 <b>Всего позиций:</b> {len(positions)} шт.",
    ]
    return "\n".join(lines)


def build_positions_text(
    account: dict, snapshot: dict, page: int = 1, page_size: int = 5
) -> tuple[str, int]:
    """Формирует постраничный список позиций с сортировкой по весу в портфеле."""
    acc_name = account.get("name", "Основной счет")
    positions = snapshot.get("positions", [])

    if not positions:
        return (
            f"💼 <b>Счет: {acc_name}</b>\n\n"
            "ℹ️ <i>В данном портфеле нет открытых позиций в ценных бумагах (весь баланс в кэше или валюте).</i>",
            1,
        )

    # Сортируем позиции по убыванию стоимости (активы с наибольшим весом сверху)
    sorted_positions = sorted(
        positions,
        key=lambda p: float(p.get("quantity") or 0) * float(p.get("current_price") or 0),
        reverse=True,
    )

    total_count = len(sorted_positions)
    total_pages = max(1, (total_count + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * page_size
    page_positions = sorted_positions[start_idx : start_idx + page_size]

    lines = [
        f"📦 <b>Позиции в портфеле ({acc_name})</b>",
        f"<i>Всего активов: {total_count} шт. (Стр. {page}/{total_pages})</i>\n",
    ]

    for p in page_positions:
        ticker = p.get("ticker") or p.get("figi", "")
        name = p.get("name") or ticker or "Ценная бумага"
        qty = float(p.get("quantity") or 0)
        price = float(p.get("current_price") or 0)
        yield_val = p.get("expected_yield")
        total_pos = qty * price

        type_raw = str(p.get("instrument_type") or "").lower()
        if "share" in type_raw:
            type_icon = "📈"
        elif "bond" in type_raw:
            type_icon = "🏛"
        elif "etf" in type_raw:
            type_icon = "📊"
        else:
            type_icon = "💵"

        ticker_display = f" (<code>{ticker}</code>)" if ticker and ticker != name else ""

        lines.append(
            f"{type_icon} <b>{name}</b>{ticker_display}\n"
            f"   ├ Количество: <b>{qty:g} шт.</b>\n"
            f"   ├ Стоимость: <b>{format_currency(total_pos)}</b> ({format_currency(price)} / шт.)\n"
            f"   └ PnL: {format_yield(yield_val)}\n"
        )

    return "\n".join(lines), total_pages


def build_risk_audit_text(account: dict, snapshot: dict) -> str:
    """Проводит экспресс-аудит рисков и концентрации активов."""
    acc_name = account.get("name", "Основной счет")
    total = float(snapshot.get("total_amount_portfolio") or 0)
    currencies = float(snapshot.get("total_amount_currencies") or 0)
    shares = float(snapshot.get("total_amount_shares") or 0)
    bonds = float(snapshot.get("total_amount_bonds") or 0)
    positions = snapshot.get("positions", [])

    lines = [
        f"⚠️ <b>Экспресс-аудит рисков ({acc_name})</b>\n",
        "<b>1. Диверсификация классов активов:</b>",
    ]

    if total == 0:
        lines.append("• Баланс портфеля нулевой. Аудит не требуется.")
        return "\n".join(lines)

    cash_ratio = (currencies / total) * 100.0
    shares_ratio = (shares / total) * 100.0
    bonds_ratio = (bonds / total) * 100.0

    if cash_ratio > 80.0:
        lines.append(f"🔴 <b>Критическая доля кэша: {cash_ratio:.1f}%</b>. Средства не защищены от инфляции.")
    elif cash_ratio > 30.0:
        lines.append(f"🟡 <b>Высокая доля кэша: {cash_ratio:.1f}%</b>. Возможно, избыточная ликвидность.")
    else:
        lines.append(f"🟢 <b>Доля кэша в норме: {cash_ratio:.1f}%</b>.")

    lines.append("\n<b>2. Концентрация эмитентов:</b>")
    high_concentration = []
    for p in positions:
        qty = float(p.get("quantity") or 0)
        price = float(p.get("current_price") or 0)
        pos_total = qty * price
        ratio = (pos_total / total) * 100.0 if total > 0 else 0
        if ratio > 25.0:
            high_concentration.append((p.get("ticker") or p.get("name"), ratio))

    if high_concentration:
        for ticker, ratio in high_concentration:
            lines.append(f"🔴 <b>{ticker}</b> занимает <b>{ratio:.1f}%</b> портфеля (>25% порога риска).")
    else:
        lines.append("🟢 Критической концентрации в отдельных бумагах не обнаружено.")

    lines.append(f"\n<b>3. Итоговый статус риска:</b>")
    if cash_ratio > 80.0 or high_concentration:
        lines.append("⚠️ <b>Требуется балансировка</b>.")
    else:
        lines.append("✅ <b>Умеренный / сбалансированный профиль</b>.")

    return "\n".join(lines)

def build_analytics_text(data: dict) -> str:
    if not data:
        return "❌ <i>Данные аналитики пока недоступны.</i>"

    account_name = data.get("account_name", "Счёт")
    risk_level = data.get("risk_level", "Нет данных")
    volatility = float(data.get("annual_volatility") or 0.0)
    max_dd = float(data.get("max_drawdown") or 0.0)
    sharpe = float(data.get("sharpe_ratio") or 0.0)

    # 1. Интерпретация волатильности
    if volatility == 0.0:
        vol_verdict = "<i>(идёт накопление истории котировок)</i>"
    elif volatility < 8.0:
        vol_verdict = "🟢 <i>Низкая (портфель стабилен, как ОФЗ или фонды ликвидности)</i>"
    elif volatility < 20.0:
        vol_verdict = "🟡 <i>Умеренная (нормальный рыночный риск акций РФ)</i>"
    else:
        vol_verdict = "🔴 <i>Высокая (сильные ценовые горки, повышенный риск)</i>"

    # 2. Интерпретация максимальной просадки (mDD)
    if max_dd == 0.0:
        dd_verdict = "🟢 <i>Падений от пика не зафиксировано</i>"
    elif abs(max_dd) < 3.0:
        dd_verdict = f"🟢 <i>Микро-колебания ({max_dd:.2f}% от пика, стабильно)</i>"
    elif abs(max_dd) < 15.0:
        dd_verdict = f"🟡 <i>Рабочая коррекция ({max_dd:.2f}% от пика)</i>"
    else:
        dd_verdict = f"🔴 <i>Глубокая просадка ({max_dd:.2f}%, тест на крепость нервов)</i>"

    # 3. Интерпретация коэффициента Шарпа
    if sharpe == 0.0:
        sharpe_verdict = "<i>(считается при накоплении данных от 3+ дней)</i>"
    elif sharpe < 0:
        sharpe_verdict = "🔴 <i>Хуже вклада под 19% (риск акций пока не окупается)</i>"
    elif sharpe < 1.0:
        sharpe_verdict = "🟡 <i>Слабая отдача (доходность есть, но риск велик)</i>"
    elif sharpe < 2.0:
        sharpe_verdict = "🟢 <i>Хорошо (риск полностью окупается доходностью)</i>"
    else:
        sharpe_verdict = "🏆 <i>Превосходно (высочайшая отдача на единицу риска)</i>"

    progress_bar = format_progress_bar(volatility, 100.0)

    text = (
        f"📊 <b>Аналитический аудит: {account_name}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🛡 <b>Риск-профиль:</b> <b>{risk_level}</b>\n\n"
        f"📈 <b>Годовая волатильность:</b> <code>{volatility:.2f}%</code>\n"
        f"   └ {vol_verdict}\n"
        f"   {progress_bar}\n\n"
        f"📉 <b>Макс. просадка (mDD):</b> <code>{max_dd:.2f}%</code>\n"
        f"   └ {dd_verdict}\n\n"
        f"🧮 <b>Коэффициент Шарпа:</b> <code>{sharpe:.3f}</code>\n"
        f"   └ {sharpe_verdict}\n\n"
    )

    sectors = data.get("sector_allocation", {})
    if sectors:
        text += "🍕 <b>Структура портфеля:</b>\n"
        for sector, ratio in sectors.items():
            percentage = round(ratio * 100, 1)
            text += f"  ▪️ {sector.upper()}: <code>{percentage}%</code>\n"
        text += "\n"

    concentration = data.get("concentration_risk", [])
    critical_positions = [p for p in concentration if p.get("is_critical", False)]

    if critical_positions:
        text += "⚠️ <b>Риск высокой концентрации!</b>\n"
        text += "Следующие активы занимают более 25% портфеля:\n"
        for pos in critical_positions:
            pos_ratio = round(pos.get("ratio", 0.0) * 100, 1)
            name_str = f" ({pos['name']})" if pos.get("name") else ""
            text += f"  ❌ <b>{pos['ticker']}</b>{name_str} — <code>{pos_ratio}%</code>\n"
    else:
        text += "✅ <b>Диверсификация в норме:</b> критических перекосов в топ-активах не обнаружено.\n"

    return text
