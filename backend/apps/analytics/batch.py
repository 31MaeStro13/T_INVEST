"""
Высокопроизводительный матричный Batch-движок аналитики на NumPy.

Рассчитывает финансовые метрики (волатильность, mDD, Шарп) одновременно
для сотен и тысяч инвесторов в одном 2D массиве (без циклов Python).
Использует векторные инструкции процессора (SIMD / NEON на ARM).
"""

from __future__ import annotations
import numpy as np

TRADING_DAYS_YEAR = 252


def compute_batch_metrics(equity_matrix: np.ndarray, risk_free_rate: float = 0.19) -> dict[str, np.ndarray]:
    """
    Одновременный расчёт метрик по пачке портфелей.

    equity_matrix: 2D np.ndarray формы (N_portfolios, T_snapshots)
                   dtype=float64, непрерывный в памяти (C-contiguous).
    risk_free_rate: безрисковая ставка (ключевая ставка ЦБ РФ, 0.19 = 19%).

    Возвращает dict с массивами размера (N_portfolios,):
      - 'annual_volatilities': годовая волатильность в %
      - 'max_drawdowns': максимальная просадка в %
      - 'sharpe_ratios': коэффициент Шарпа
      - 'mean_annual_returns': среднегодовая доходность в %
    """
    # Гарантируем C-contiguous float64 для векторных инструкций
    arr = np.ascontiguousarray(equity_matrix, dtype=np.float64)
    n_portfolios, n_periods = arr.shape

    if n_periods < 3:
        zeros = np.zeros(n_portfolios, dtype=np.float64)
        return {
            "annual_volatilities": zeros,
            "max_drawdowns": zeros,
            "sharpe_ratios": zeros,
            "mean_annual_returns": zeros,
        }

    # 1. 2D Векторизованный Max Drawdown (mDD)
    # running maximum вдоль оси времени (axis=1)
    peaks = np.maximum.accumulate(arr, axis=1)
    # Просадки в каждый момент времени: (arr - peak) / peak
    with np.errstate(divide="ignore", invalid="ignore"):
        drawdowns = np.where(peaks > 0, (arr - peaks) / peaks, 0.0)
    # Минимальная просадка по каждому портфелю
    max_dd = np.nanmin(drawdowns, axis=1) * 100.0  # в процентах

    # 2. 2D Векторизованные лог-доходности
    # diff вдоль временной оси
    with np.errstate(divide="ignore", invalid="ignore"):
        clean_arr = np.where(arr <= 0, np.nan, arr)
        log_arr = np.log(clean_arr)
        r = np.diff(log_arr, axis=1)

    # 3. Волатильность и доходность
    # ddof=1 для несмещенной дисперсии выборки
    r_std = np.nanstd(r, axis=1, ddof=1)
    annual_vol = r_std * np.sqrt(TRADING_DAYS_YEAR) * 100.0  # в процентах

    r_mean = np.nanmean(r, axis=1)
    annual_return = r_mean * TRADING_DAYS_YEAR

    # 4. Коэффициент Шарпа: (R_annual - Rf) / Vol_annual_fraction
    vol_fractions = annual_vol / 100.0
    with np.errstate(divide="ignore", invalid="ignore"):
        sharpe = np.where(
            vol_fractions > 1e-6,
            (annual_return - risk_free_rate) / vol_fractions,
            0.0,
        )

    return {
        "annual_volatilities": np.round(annual_vol, 2),
        "max_drawdowns": np.round(max_dd, 2),
        "sharpe_ratios": np.round(sharpe, 3),
        "mean_annual_returns": np.round(annual_return * 100.0, 2),
    }
