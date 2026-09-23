import unittest
from .engine import (
    annual_volatility,
    compute_all,
    concentration_risk,
    max_drawdown,
    sector_allocation,
    sharpe_ratio,
)


class AnalyticsEngineTestCase(unittest.TestCase):
    """Модульные тесты финансового NumPy-ядра без обращения к базе данных."""

    def test_max_drawdown_flat_equity(self):
        """Максимальная просадка для постоянного портфеля равна 0.0."""
        equity = [100.0, 100.0, 100.0, 100.0]
        self.assertEqual(max_drawdown(equity), 0.0)

    def test_max_drawdown_typical(self):
        """Просадка с 100 до 80 (-20%)."""
        equity = [100.0, 110.0, 88.0, 95.0]  # Пик 110 -> спад до 88: (88-110)/110 = -0.2 (-20%)
        mdd = max_drawdown(equity)
        self.assertAlmostEqual(mdd, -0.2, places=4)

    def test_max_drawdown_insufficient_periods(self):
        """Меньше 3 снимков -> возврат 0.0."""
        self.assertEqual(max_drawdown([100.0, 90.0]), 0.0)
        self.assertEqual(max_drawdown([]), 0.0)

    def test_annual_volatility_flat_equity(self):
        """Для плоской стоимости волатильность равна 0.0."""
        equity = [100.0, 100.0, 100.0, 100.0]
        self.assertEqual(annual_volatility(equity), 0.0)

    def test_annual_volatility_positive_on_fluctuations(self):
        """Для колеблющегося портфеля годовая волатильность строго положительна."""
        equity = [100.0, 102.0, 98.0, 101.0, 99.0]
        vol = annual_volatility(equity)
        self.assertGreater(vol, 0.0)

    def test_sharpe_ratio_insufficient_periods(self):
        """При недостатке истории Шарп равен 0.0."""
        self.assertEqual(sharpe_ratio([100.0, 105.0]), 0.0)

    def test_sector_allocation_percentages(self):
        """Корректность подсчета долей классов активов."""
        positions = [
            {"instrument_type": "share", "quantity": 10, "current_price": 50},   # 500
            {"instrument_type": "bond", "quantity": 2, "current_price": 100},    # 200
            {"instrument_type": "share", "quantity": 5, "current_price": 60},    # 300
        ]
        # Total = 1000: shares = 800 (80%), bonds = 200 (20%)
        alloc = sector_allocation(positions)
        self.assertEqual(alloc["share"], 0.8)
        self.assertEqual(alloc["bond"], 0.2)

    def test_sector_allocation_empty(self):
        """Пустые позиции отдают пустой словарь."""
        self.assertEqual(sector_allocation([]), {})

    def test_concentration_risk_critical_flag(self):
        """Активы с долей > 25% помечаются как критические."""
        positions = [
            {"ticker": "SBER", "name": "Сбер", "quantity": 4, "current_price": 100},  # 400 (40% > 25%)
            {"ticker": "GAZP", "name": "Газпром", "quantity": 3, "current_price": 100}, # 300 (30% > 25%)
            {"ticker": "LKOH", "name": "Лукойл", "quantity": 2, "current_price": 100},  # 200 (20% <= 25%)
            {"ticker": "OFZ", "name": "ОФЗ", "quantity": 1, "current_price": 100},     # 100 (10% <= 25%)
        ]
        res = concentration_risk(positions)
        self.assertEqual(len(res), 4)
        # Отсортировано по убыванию
        self.assertEqual(res[0]["ticker"], "SBER")
        self.assertTrue(res[0]["is_critical"])
        self.assertTrue(res[1]["is_critical"])
        self.assertFalse(res[2]["is_critical"])
        self.assertFalse(res[3]["is_critical"])

    def test_compute_all_report_structure(self):
        """Комплексный расчет возвращает все необходимые ключи и вердикт."""
        equity = [100000.0, 100500.0, 99800.0, 100200.0]
        positions = [
            {"instrument_type": "share", "ticker": "SBER", "name": "Сбер", "quantity": 10, "current_price": 300}
        ]
        data = compute_all(equity, positions, risk_free_rate=0.19)
        self.assertIn("max_drawdown", data)
        self.assertIn("annual_volatility", data)
        self.assertIn("sharpe_ratio", data)
        self.assertIn("risk_level", data)
        self.assertIn("sector_allocation", data)
        self.assertIn("concentration_risk", data)
        self.assertTrue(data["has_sufficient_data"])

    def test_compute_batch_metrics_equivalence(self):
        """Проверка численной эквивалентности 2D матричного батчинга и 1D ядра."""
        import numpy as np
        from .batch import compute_batch_metrics

        p1 = [100.0, 105.0, 95.0, 102.0]
        p2 = [200.0, 210.0, 190.0, 204.0]
        matrix = np.array([p1, p2])

        batch_res = compute_batch_metrics(matrix, risk_free_rate=0.19)

        # Проверяем для портфеля 1
        vol_1d = round(annual_volatility(p1) * 100, 2)
        mdd_1d = round(max_drawdown(p1) * 100, 2)
        sharpe_1d = round(sharpe_ratio(p1, 0.19), 3)

        self.assertEqual(batch_res["annual_volatilities"][0], vol_1d)
        self.assertEqual(batch_res["max_drawdowns"][0], mdd_1d)
        self.assertEqual(batch_res["sharpe_ratios"][0], sharpe_1d)

        # Проверяем размерность результата
        self.assertEqual(len(batch_res["annual_volatilities"]), 2)

