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


def build_positions_text(account: dict, snapshot: dict) -> str:
    """Формирует подробный список активов портфеля."""
    acc_name = account.get("name", "Основной счет")
    positions = snapshot.get("positions", [])

    if not positions:
        return (
            f"💼 <b>Счет: {acc_name}</b>\n\n"
            "ℹ️ <i>В данном портфеле нет открытых позиций в ценных бумагах (весь баланс в кэше или валюте).</i>"
        )

    lines = [
        f"📦 <b>Позиции в портфеле ({acc_name}):</b>\n",
    ]

    for p in positions:
        name = p.get("name") or "Неизвестный инструмент"
        ticker = p.get("ticker") or p.get("figi", "")
        qty = float(p.get("quantity") or 0)
        price = float(p.get("current_price") or 0)
        yield_val = p.get("expected_yield")
        total_pos = qty * price

        type_icon = "📈" if p.get("instrument_type") == "share" else "🏛"

        lines.append(
            f"{type_icon} <b>{name}</b> (<code>{ticker}</code>)\n"
            f"   ├ Количество: <b>{qty:g} шт.</b>\n"
            f"   ├ Стоимость: <b>{format_currency(total_pos)}</b> ({format_currency(price)} / шт.)\n"
            f"   └ PnL: {format_yield(yield_val)}\n"
        )

    return "\n".join(lines)


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
