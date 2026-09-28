"""
excel_parser.py — In-Memory потоковый парсер брокерских отчетов (.xlsx) Т-Банка и брокеров РФ.

Архитектурный принцип (Zero-Disk Footprint):
1. Файл читается исключительно в оперативной памяти (RAM) через openpyxl (read_only=True).
2. На диск не записывается ни байта (отсутствие временных файлов / tempfile).
3. Позиции и метрики риска рассчитываются "на лету" через NumPy.
4. Персональные данные и номера брокерских счетов не сохраняются в БД.
"""

import io
import logging
from typing import Any

import numpy as np
import openpyxl

logger = logging.getLogger(__name__)

# Синонимы колонок для гибкого парсинга отчетов разных брокеров
COLUMN_SYNONYMS = {
    "ticker": ["тикер", "код", "код инструмента", "ticker", "symbol", "инструмент (код)"],
    "name": ["наименование", "название", "эмитент", "краткое наименование", "name", "security"],
    "quantity": ["количество", "кол-во", "кол-во шт.", "кол-во шт", "остаток", "quantity", "qty"],
    "price": ["текущая цена", "цена", "рыночная цена", "цена закрытия", "price", "last_price"],
    "total_value": [
        "стоимость",
        "рыночная стоимость",
        "сумма",
        "оценка",
        "стоимость позиции",
        "total",
        "value",
        "amount",
    ],
    "instrument_type": ["вид", "тип", "категория", "класс актива", "тип инструмента", "type"],
}


def _classify_instrument(raw_type: str, ticker: str, name: str) -> str:
    """Нормализует тип финансового инструмента к стандарту (share, bond, etf, currency)."""
    text = f"{raw_type} {ticker} {name}".lower()

    if any(k in text for k in ["облигац", "бонд", "офз", "sub", "bond"]):
        return "bond"
    if any(k in text for k in ["etf", "фонд", "бпиф", "пай", "индекс"]):
        return "etf"
    if any(k in text for k in ["валют", "rub", "usd", "eur", "cny", "рубл", "доллар", "юань"]):
        return "currency"
    if any(k in text for k in ["акци", "share", "stock"]):
        return "share"
    return "share"  # по умолчанию


def parse_broker_report_xlsx(file_content: bytes | io.BytesIO) -> dict[str, Any]:
    """
    Парсит .xlsx брокерский отчет в RAM, извлекает позиции и считает метрики риска.

    :param file_content: бинарный поток или BytesIO файла Excel.
    :return: структурированный словарь с позициями, долями и метриками концентрации.
    :raises ValueError: если отчет не удалось распознать или файл поврежден.
    """
    if isinstance(file_content, bytes):
        stream = io.BytesIO(file_content)
    else:
        stream = file_content

    try:
        wb = openpyxl.load_workbook(stream, read_only=True, data_only=True)
    except Exception as exc:
        logger.error(f"Ошибка чтения Excel-файла: {exc}")
        raise ValueError("Не удалось открыть файл. Убедитесь, что это корректный документ Excel (.xlsx).") from exc

    sheet = None
    target_keywords = ["портфель", "актив", "сводка", "остатк", "отчет", "позици"]
    for s_name in wb.sheetnames:
        if any(kw in s_name.lower() for kw in target_keywords):
            sheet = wb[s_name]
            break
    if not sheet:
        sheet = wb.active

    if not sheet:
        raise ValueError("В Excel-файле не найдено рабочих листов с данными.")

    # 1. Поиск строки с заголовками
    col_mapping: dict[str, int] = {}
    header_row_idx = None

    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        raise ValueError("Файл Excel пуст.")

    for row_idx, row in enumerate(rows[:25]):
        if not row:
            continue
        row_str_cells = [str(c).strip().lower() if c is not None else "" for c in row]
        matches = 0
        temp_map = {}

        for field, synonyms in COLUMN_SYNONYMS.items():
            for col_idx, cell_val in enumerate(row_str_cells):
                if any(syn in cell_val for syn in synonyms):
                    temp_map[field] = col_idx
                    matches += 1
                    break

        # Если нашли минимум 2 ключевые колонки (например, тикер/имя и количество/цена)
        if matches >= 2 and ("ticker" in temp_map or "name" in temp_map):
            col_mapping = temp_map
            header_row_idx = row_idx
            break

    # Фоллбэк: если специфических заголовков нет, используем дефолтные позиции колонок
    if header_row_idx is None:
        # Предполагаем формат: A=Ticker, B=Name, C=Qty, D=Price, E=Total, F=Type
        col_mapping = {
            "ticker": 0,
            "name": 1,
            "quantity": 2,
            "price": 3,
            "total_value": 4,
            "instrument_type": 5,
        }
        header_row_idx = 0

    # 2. Извлечение позиций
    positions: list[dict[str, Any]] = []

    for row in rows[header_row_idx + 1:]:
        if not row or all(c is None for c in row):
            continue

        def get_val(field: str, default=None):
            idx = col_mapping.get(field)
            if idx is not None and idx < len(row):
                return row[idx]
            return default

        raw_ticker = str(get_val("ticker") or "").strip()
        raw_name = str(get_val("name") or "").strip()

        # Игнорируем строки итогов и мусор
        if any(ign in (raw_ticker + raw_name).lower() for ign in ["итого", "всего", "total", "сумма"]):
            continue

        raw_qty = get_val("quantity")
        raw_price = get_val("price")
        raw_total = get_val("total_value")
        raw_type = str(get_val("instrument_type") or "").strip()

        # Парсинг чисел
        def parse_float(val) -> float:
            if val is None:
                return 0.0
            if isinstance(val, (int, float)):
                return float(val)
            s = str(val).replace(" ", "").replace(",", ".").replace("\xa0", "").strip()
            try:
                return float(s)
            except ValueError:
                return 0.0

        quantity = parse_float(raw_qty)
        price = parse_float(raw_price)
        total_val = parse_float(raw_total)

        if total_val <= 0.0 and quantity > 0 and price > 0:
            total_val = round(quantity * price, 2)
        elif price <= 0.0 and quantity > 0 and total_val > 0:
            price = round(total_val / quantity, 2)

        # Если ни тикера, ни имени, ни стоимости — пропускаем
        if not raw_ticker and not raw_name:
            continue
        if total_val <= 0.0 and quantity <= 0.0:
            continue

        ticker = raw_ticker or raw_name[:12].upper()
        name = raw_name or raw_ticker
        inst_type = _classify_instrument(raw_type, ticker, name)

        positions.append({
            "ticker": ticker,
            "name": name,
            "instrument_type": inst_type,
            "quantity": quantity,
            "current_price": price,
            "total_value": total_val,
        })

    wb.close()

    if not positions:
        raise ValueError(
            "Не удалось извлечь активы из отчета. Проверьте формат таблицы (должны быть колонки Тикер, Количество, Цена/Стоимость)."
        )

    # 3. Расчет метрик риска и структуры через NumPy
    values = np.array([p["total_value"] for p in positions], dtype=np.float64)
    total_portfolio_value = float(np.sum(values))

    if total_portfolio_value > 0:
        weights = values / total_portfolio_value
        for i, pos in enumerate(positions):
            pos["weight"] = round(float(weights[i]) * 100, 2)
    else:
        for pos in positions:
            pos["weight"] = 0.0

    # Агрегация по классам активов
    shares_sum = sum(p["total_value"] for p in positions if p["instrument_type"] == "share")
    bonds_sum = sum(p["total_value"] for p in positions if p["instrument_type"] == "bond")
    etf_sum = sum(p["total_value"] for p in positions if p["instrument_type"] == "etf")
    currencies_sum = sum(p["total_value"] for p in positions if p["instrument_type"] == "currency")

    # Сортировка позиций по убыванию стоимости
    positions.sort(key=lambda x: x["total_value"], reverse=True)

    # Индекс концентрации Герфиндаля-Хиршмана (HHI) = sum(w_i_percent ** 2)
    # HHI < 1500 — низкая концентрация (отличная диверсификация)
    # 1500..2500 — умеренная
    # > 2500 — высокая концентрация (риск)
    if total_portfolio_value > 0:
        hhi = float(np.sum((weights * 100) ** 2))
        top_asset_share = float(positions[0]["weight"]) if positions else 0.0
        top_5_share = float(sum(p["weight"] for p in positions[:5]))
    else:
        hhi = 0.0
        top_asset_share = 0.0
        top_5_share = 0.0

    if hhi < 1500:
        concentration_risk = "low"
        risk_label = "Низкая концентрация (Хорошая диверсификация)"
    elif hhi < 2500:
        concentration_risk = "medium"
        risk_label = "Умеренная концентрация"
    else:
        concentration_risk = "high"
        risk_label = "Высокая концентрация (Повышенный риск)"

    return {
        "status": "success",
        "total_amount_portfolio": round(total_portfolio_value, 2),
        "positions_count": len(positions),
        "asset_breakdown": {
            "shares": round(shares_sum, 2),
            "bonds": round(bonds_sum, 2),
            "etf": round(etf_sum, 2),
            "currencies": round(currencies_sum, 2),
        },
        "asset_percentages": {
            "shares": round((shares_sum / total_portfolio_value * 100), 2) if total_portfolio_value > 0 else 0,
            "bonds": round((bonds_sum / total_portfolio_value * 100), 2) if total_portfolio_value > 0 else 0,
            "etf": round((etf_sum / total_portfolio_value * 100), 2) if total_portfolio_value > 0 else 0,
            "currencies": round((currencies_sum / total_portfolio_value * 100), 2) if total_portfolio_value > 0 else 0,
        },
        "risk_metrics": {
            "hhi_index": round(hhi, 1),
            "concentration_level": concentration_risk,
            "concentration_label": risk_label,
            "top_asset_share_pct": round(top_asset_share, 2),
            "top_5_share_pct": round(top_5_share, 2),
        },
        "positions": positions,
    }
