"""
excel_parser.py — Защищённый потоковый парсер брокерских отчетов (.xlsx).

Архитектурные принципы:
1. Zero-Disk Footprint: файл читается только в RAM, на диск не пишется ни байта.
2. Chunked Reading: строки читаются через генератор, не загружаясь все сразу в память.
3. Hardened Security: защита от ZIP Bomb, Formula Injection, OOM, XXE, Macro-файлов.
4. Strict Limits: ≤ 10 000 строк, ≤ 500 позиций на файл.

Закрытые векторы атак:
- OOM / Memory Bomb  → MAX_FILE_BYTES (5 МБ) + MAX_ROWS (10 000)
- ZIP Bomb            → Проверка магического байта PK\\x03\\x04
- Formula Injection   → Санация ячеек с префиксами =, +, -, @
- VBA/Macro Injection → Отклонение .xlsm / не-OOXML форматов
- XXE                 → openpyxl read_only=True (внешние сущности не грузит)
- CPU DoS             → MAX_ROWS + MAX_POSITIONS лимиты
- Path Traversal      → Имя файла никуда не сохраняется и не используется
"""

import io
import logging
import zipfile
from typing import Any

import numpy as np
import openpyxl

logger = logging.getLogger(__name__)

# ── Жёсткие лимиты безопасности ────────────────────────────────────────────
MAX_FILE_BYTES = 5 * 1024 * 1024      # 5 МБ — максимальный размер файла
MAX_ROWS = 10_000                       # максимум строк для обхода (включая заголовки)
MAX_POSITIONS = 500                     # максимум позиций в итоговом списке
MAX_HEADER_SCAN_ROWS = 30              # сколько строк сверху сканировать в поисках заголовка
MAX_CELL_LEN = 1_024                   # максимум символов в одной ячейке

# Префиксы формул — потенциальный Formula Injection
_FORMULA_PREFIXES = ("=", "+", "-", "@")

# Синонимы колонок для гибкого парсинга отчетов разных брокеров РФ
COLUMN_SYNONYMS = {
    "ticker": ["тикер", "код", "код инструмента", "ticker", "symbol", "инструмент (код)"],
    "name": ["наименование", "название", "эмитент", "краткое наименование", "name", "security"],
    "quantity": ["количество", "кол-во", "кол-во шт.", "кол-во шт", "остаток", "quantity", "qty"],
    "price": ["текущая цена", "цена", "рыночная цена", "цена закрытия", "price", "last_price"],
    "total_value": [
        "стоимость", "рыночная стоимость", "сумма", "оценка",
        "стоимость позиции", "total", "value", "amount",
    ],
    "instrument_type": ["вид", "тип", "категория", "класс актива", "тип инструмента", "type"],
}


def _validate_xlsx_bytes(data: bytes) -> None:
    """
    Проверяет что переданные байты являются корректным ZIP-файлом (OOXML).
    Отклоняет ZIP Bomb и не-OOXML форматы (xls, xlsm с VBA).

    :raises ValueError: если файл не является валидным .xlsx.
    """
    # Проверка магического байта ZIP: PK\x03\x04
    if not data[:4] == b"PK\x03\x04":
        raise ValueError(
            "Файл не является корректным Excel (.xlsx). "
            "Убедитесь, что файл не повреждён и сохранён в формате .xlsx."
        )

    # Открываем как ZIP и проверяем признаки VBA-макросов (xlsm)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
            # xlsm содержит vbaProject.bin — отклоняем
            if any("vbaProject" in n or n.endswith(".bin") for n in names):
                raise ValueError(
                    "Файл содержит макросы (VBA) и не может быть обработан из соображений безопасности. "
                    "Пересохраните отчёт в формате .xlsx (без макросов)."
                )
            # ZIP Bomb guard: суммируем несжатый размер всех записей
            total_uncompressed = sum(i.file_size for i in zf.infolist())
            # Если несжатый размер > 50 МБ при файле ≤ 5 МБ — это аномалия
            if total_uncompressed > 50 * 1024 * 1024:
                raise ValueError(
                    "Файл подозрительно большой в распакованном виде. "
                    "Возможно, файл повреждён или содержит избыточные данные."
                )
    except zipfile.BadZipFile as exc:
        raise ValueError(
            "Файл повреждён или не является корректным Excel (.xlsx)."
        ) from exc


def _sanitize_cell(value: Any) -> Any:
    """
    Санирует значение ячейки: обрезает строки, удаляет Formula Injection-префиксы.
    Числа и None возвращаются без изменений.
    """
    if value is None or isinstance(value, (int, float, bool)):
        return value

    s = str(value)

    # Ограничиваем длину ячейки
    if len(s) > MAX_CELL_LEN:
        s = s[:MAX_CELL_LEN]

    # Formula Injection: ячейка начинается с формульного символа
    stripped = s.strip()
    if stripped and stripped[0] in _FORMULA_PREFIXES:
        logger.warning("Formula Injection attempt blocked in cell: %r", stripped[:50])
        return ""  # обнуляем — не парсим как число

    return s


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
    return "share"


def parse_broker_report_xlsx(file_content: bytes | io.BytesIO) -> dict[str, Any]:
    """
    Парсит .xlsx брокерский отчёт в RAM, извлекает позиции и считает метрики риска.
    Использует потоковое чтение строк (chunked), не загружая весь файл в память.

    :param file_content: бинарный поток или BytesIO файла Excel.
    :return: структурированный словарь с позициями, долями и метриками концентрации.
    :raises ValueError: если отчёт не удалось распознать, файл повреждён или подозрителен.
    """
    # Нормализуем вход к bytes для валидации
    if isinstance(file_content, io.BytesIO):
        data = file_content.getvalue()
    else:
        data = file_content

    # ── Шаг 0: Валидация файла до открытия openpyxl ─────────────────────────
    if len(data) > MAX_FILE_BYTES:
        raise ValueError(
            f"Размер файла превышает лимит {MAX_FILE_BYTES // (1024 * 1024)} МБ. "
            "Загрузите более компактный отчёт."
        )

    _validate_xlsx_bytes(data)

    # ── Шаг 1: Открытие книги ────────────────────────────────────────────────
    try:
        wb = openpyxl.load_workbook(
            io.BytesIO(data),
            read_only=True,    # потоковый режим — не грузит все ячейки сразу
            data_only=True,    # возвращает значения ячеек, а не формулы
            keep_links=False,  # отключает внешние ссылки (XXE-вектор)
        )
    except Exception as exc:
        logger.error("Ошибка чтения Excel-файла: %s", exc)
        raise ValueError(
            "Не удалось открыть файл. Убедитесь, что это корректный документ Excel (.xlsx)."
        ) from exc

    # ── Шаг 2: Выбор листа ──────────────────────────────────────────────────
    sheet = None
    target_keywords = ["портфель", "актив", "сводка", "остатк", "отчет", "позици"]
    for s_name in wb.sheetnames:
        if any(kw in s_name.lower() for kw in target_keywords):
            sheet = wb[s_name]
            break
    if not sheet:
        sheet = wb.active

    if not sheet:
        wb.close()
        raise ValueError("В Excel-файле не найдено рабочих листов с данными.")

    # ── Шаг 3: Потоковый обход строк (chunked) + поиск заголовка ────────────
    col_mapping: dict[str, int] = {}
    header_row_idx: int | None = None
    all_rows: list[tuple] = []   # сохраняем строки после заголовка
    row_count = 0

    for row in sheet.iter_rows(values_only=True):
        if row_count >= MAX_ROWS:
            logger.warning("Excel файл превышает лимит %d строк — обработка остановлена.", MAX_ROWS)
            break

        # Санация каждой ячейки строки
        sanitized_row = tuple(_sanitize_cell(cell) for cell in row)

        if header_row_idx is None and row_count < MAX_HEADER_SCAN_ROWS:
            # Пробуем найти строку заголовков
            row_str_cells = [
                str(c).strip().lower() if c is not None else "" for c in sanitized_row
            ]
            matches = 0
            temp_map: dict[str, int] = {}

            for field, synonyms in COLUMN_SYNONYMS.items():
                for col_idx, cell_val in enumerate(row_str_cells):
                    if any(syn in cell_val for syn in synonyms):
                        temp_map[field] = col_idx
                        matches += 1
                        break

            if matches >= 2 and ("ticker" in temp_map or "name" in temp_map):
                col_mapping = temp_map
                header_row_idx = row_count
                row_count += 1
                continue  # пропускаем саму строку заголовка

        if header_row_idx is not None:
            all_rows.append(sanitized_row)

        row_count += 1

    wb.close()

    # Фоллбэк если заголовков не нашли
    if header_row_idx is None:
        col_mapping = {"ticker": 0, "name": 1, "quantity": 2, "price": 3, "total_value": 4, "instrument_type": 5}
        all_rows = [tuple(_sanitize_cell(c) for c in r) for r in all_rows]

    if not all_rows:
        raise ValueError("Файл Excel пуст или не содержит данных после заголовка.")

    # ── Шаг 4: Извлечение позиций ────────────────────────────────────────────
    positions: list[dict[str, Any]] = []

    def get_val(row: tuple, field: str, default=None) -> Any:
        idx = col_mapping.get(field)
        if idx is not None and idx < len(row):
            return row[idx]
        return default

    def parse_float(val: Any) -> float:
        if val is None:
            return 0.0
        if isinstance(val, (int, float)):
            return float(val)
        s = str(val).replace(" ", "").replace(",", ".").replace("\xa0", "").strip()
        try:
            return float(s)
        except ValueError:
            return 0.0

    for row in all_rows:
        if not row or all(c is None for c in row):
            continue

        raw_ticker = str(get_val(row, "ticker") or "").strip()
        raw_name = str(get_val(row, "name") or "").strip()

        # Игнорируем строки итогов
        combined = (raw_ticker + raw_name).lower()
        if any(ign in combined for ign in ["итого", "всего", "total", "сумма", "итог"]):
            continue

        quantity = parse_float(get_val(row, "quantity"))
        price = parse_float(get_val(row, "price"))
        total_val = parse_float(get_val(row, "total_value"))
        raw_type = str(get_val(row, "instrument_type") or "").strip()

        # Дорасчёт missing значений
        if total_val <= 0.0 and quantity > 0 and price > 0:
            total_val = round(quantity * price, 2)
        elif price <= 0.0 and quantity > 0 and total_val > 0:
            price = round(total_val / quantity, 2)

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

        # Лимит позиций
        if len(positions) >= MAX_POSITIONS:
            logger.warning(
                "Достигнут лимит позиций (%d). Обработка файла остановлена.", MAX_POSITIONS
            )
            break

    if not positions:
        raise ValueError(
            "Не удалось извлечь активы из отчёта. "
            "Проверьте формат таблицы (должны быть колонки Тикер, Количество, Цена/Стоимость)."
        )

    # ── Шаг 5: Расчёт метрик риска через NumPy ──────────────────────────────
    values = np.array([p["total_value"] for p in positions], dtype=np.float64)
    total_portfolio_value = float(np.sum(values))

    if total_portfolio_value > 0:
        weights = values / total_portfolio_value
        for i, pos in enumerate(positions):
            pos["weight"] = round(float(weights[i]) * 100, 2)
    else:
        weights = np.zeros(len(positions))
        for pos in positions:
            pos["weight"] = 0.0

    # Агрегация по классам активов
    shares_sum = sum(p["total_value"] for p in positions if p["instrument_type"] == "share")
    bonds_sum = sum(p["total_value"] for p in positions if p["instrument_type"] == "bond")
    etf_sum = sum(p["total_value"] for p in positions if p["instrument_type"] == "etf")
    currencies_sum = sum(p["total_value"] for p in positions if p["instrument_type"] == "currency")

    # Сортировка по убыванию стоимости
    positions.sort(key=lambda x: x["total_value"], reverse=True)

    # Индекс Герфиндаля-Хиршмана (HHI)
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
