"""
Модуль генерации аналитических графиков портфеля на базе Matplotlib.
Работает строго в оперативной памяти (BytesIO) в headless-режиме (Agg).
"""
import io
import logging
from datetime import datetime
from decimal import Decimal

import matplotlib
# 1. Принудительный headless-бэкенд для серверов без GUI (до импорта pyplot)
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np

logger = logging.getLogger(__name__)

# Палитра Dark Fintech под интерфейс Telegram
STYLE_CONFIG = {
    "bg_color": "#18181b",        # Темный графит
    "card_color": "#27272a",      # Цвет подложки под графики
    "text_color": "#f4f4f5",      # Белый / светло-серый
    "grid_color": "#3f3f46",      # Приглушенная сетка
    "equity_line": "#38bdf8",     # Неоновый голубой
    "equity_fill": "#0284c7",     # Заливка под графиком
    "asset_colors": {
        "shares": "#3b82f6",      # Акции (Синий)
        "bonds": "#10b981",       # Облигации (Изумрудный)
        "etf": "#f59e0b",         # Фонды (Янтарный)
        "currencies": "#a855f7",  # Валюта/Кэш (Фиолетовый)
    },
}


def generate_portfolio_dashboard(
    dates: list[datetime] | np.ndarray,
    values: list[float] | np.ndarray,
    assets: dict[str, float | Decimal],
    account_name: str = "Основной счет",
) -> bytes:
    """
    Генерирует дашборд 1x2 (Equity Curve + Donut Chart) в буфер памяти BytesIO.
    Возвращает сырые байты PNG.
    """
    fig, (ax_equity, ax_donut) = plt.subplots(
        nrows=1,
        ncols=2,
        figsize=(12, 5),
        dpi=140,
        facecolor=STYLE_CONFIG["bg_color"],
    )

    try:
        # ==========================================
        # 1. СЛЕВА: Кривая капитала (Equity Curve)
        # ==========================================
        ax_equity.set_facecolor(STYLE_CONFIG["card_color"])

        if len(dates) > 0 and len(values) > 0:
            val_arr = np.asarray(values, dtype=float)

            # Линия баланса
            ax_equity.plot(
                dates,
                val_arr,
                color=STYLE_CONFIG["equity_line"],
                linewidth=2.5,
                marker="o" if len(dates) < 10 else None,
                markersize=4,
            )

            # Полупрозрачная заливка под графиком
            min_val = float(np.min(val_arr)) * 0.98 if len(val_arr) > 0 else 0.0
            ax_equity.fill_between(
                dates,
                val_arr,
                min_val,
                color=STYLE_CONFIG["equity_fill"],
                alpha=0.25,
            )

            # Форматирование дат на оси X
            ax_equity.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
            ax_equity.tick_params(axis="x", colors=STYLE_CONFIG["text_color"], rotation=30)
            ax_equity.tick_params(axis="y", colors=STYLE_CONFIG["text_color"])
        else:
            ax_equity.text(
                0.5, 0.5, "Недостаточно данных\nдля графика динамики",
                color=STYLE_CONFIG["text_color"],
                ha="center", va="center", fontsize=11,
            )

        ax_equity.set_title("Динамика стоимости (₽)", color=STYLE_CONFIG["text_color"], fontsize=12, pad=12, weight="bold")
        ax_equity.grid(True, linestyle="--", alpha=0.3, color=STYLE_CONFIG["grid_color"])
        for spine in ax_equity.spines.values():
            spine.set_color(STYLE_CONFIG["grid_color"])

        # ==========================================
        # 2. СПРАВА: Круговая диаграмма (Donut Chart)
        # ==========================================
        ax_donut.set_facecolor(STYLE_CONFIG["bg_color"])

        # Фильтруем активы с ненулевым балансом
        labels = []
        sizes = []
        colors = []

        mapping = [
            ("Акции", float(assets.get("shares_amount") or 0), STYLE_CONFIG["asset_colors"]["shares"]),
            ("Облигации", float(assets.get("bonds_amount") or 0), STYLE_CONFIG["asset_colors"]["bonds"]),
            ("ETF", float(assets.get("etf_amount") or 0), STYLE_CONFIG["asset_colors"]["etf"]),
            ("Кэш / Валюта", float(assets.get("currencies_amount") or 0), STYLE_CONFIG["asset_colors"]["currencies"]),
        ]

        for label, val, color in mapping:
            if val > 0:
                labels.append(f"{label}\n({val:,.0f} ₽)")
                sizes.append(val)
                colors.append(color)

        if sizes and sum(sizes) > 0:
            wedges, texts, autotexts = ax_donut.pie(
                sizes,
                labels=labels,
                autopct="%1.1f%%",
                pctdistance=0.75,
                startangle=140,
                colors=colors,
                textprops={"color": STYLE_CONFIG["text_color"], "fontsize": 9},
                wedgeprops={"width": 0.45, "edgecolor": STYLE_CONFIG["bg_color"], "linewidth": 2},
            )
            for autotext in autotexts:
                autotext.set_color("#ffffff")
                autotext.set_weight("bold")
        else:
            ax_donut.text(
                0.5, 0.5, "Портфель пуст",
                color=STYLE_CONFIG["text_color"],
                ha="center", va="center", fontsize=11,
            )

        ax_donut.set_title("Структура активов", color=STYLE_CONFIG["text_color"], fontsize=12, pad=12, weight="bold")

        # Общий заголовок всего дашборда
        fig.suptitle(f"Портфельный дашборд: {account_name}", color=STYLE_CONFIG["text_color"], fontsize=14, weight="bold", y=0.98)
        fig.tight_layout()

        # Сохранение в буфер памяти
        buffer = io.BytesIO()
        plt.savefig(
            buffer,
            format="png",
            bbox_inches="tight",
            facecolor=fig.get_facecolor(),
            edgecolor="none",
        )
        buffer.seek(0)
        return buffer.getvalue()

    finally:
        # Критично: освобождаем память холста Matplotlib после каждого вызова
        plt.close(fig)
