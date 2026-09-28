"""
locustfile.py — Сценарий нагрузочного тестирования T-Invest Portfolio Auditor.

Имитирует реальное поведение частных инвесторов:
1. Просмотр списка счетов и последних снимков (ORM + B-Tree индексы + prefetch_related).
2. Просмотр сводного портфеля (Consolidated Net Worth, склейка активов 6 счетов).
3. Расчет математических метрик риска (NumPy: Sharpe ratio, Max Drawdown, волатильность).
4. Запрос графического дашборда (Headless Matplotlib Agg + Redis Cache-Aside).
"""

from locust import HttpUser, task, between


class InvestorUser(HttpUser):
    # Время ожидания между действиями инвестора: от 0.5 до 2.0 секунд
    wait_time = between(0.5, 2.0)

    # Тестовый пользователь с 6 брокерскими счетами и историей снимков
    TELEGRAM_ID = 1531218972
    ACCOUNT_ID = 1

    @task(4)
    def test_accounts_list(self):
        """Просмотр списка счетов инвестора (быстрый запрос в ORM)."""
        self.client.get(
            f"/api/v1/accounts/?telegram_id={self.TELEGRAM_ID}",
            name="/api/v1/accounts/",
        )

    @task(3)
    def test_latest_snapshot(self):
        """Просмотр снимка счета со списком 40+ акций (prefetch_related)."""
        self.client.get(
            f"/api/v1/accounts/{self.ACCOUNT_ID}/latest_snapshot/",
            name="/api/v1/accounts/[id]/latest_snapshot/",
        )

    @task(3)
    def test_consolidated_snapshot(self):
        """Агрегация портфеля по всем счетам (Map-Reduce склейка активов в памяти)."""
        self.client.get(
            f"/api/v1/accounts/consolidated_snapshot/?telegram_id={self.TELEGRAM_ID}",
            name="/api/v1/accounts/consolidated_snapshot/",
        )

    @task(2)
    def test_risk_analytics(self):
        """Математический аудит рисков на NumPy (Шарп, mDD, волатильность)."""
        self.client.get(
            f"/api/v1/analytics/consolidated/?telegram_id={self.TELEGRAM_ID}",
            name="/api/v1/analytics/consolidated/",
        )

    @task(1)
    def test_portfolio_chart(self):
        """Запрос аналитического графика (Matplotlib в RAM + Redis кэш)."""
        self.client.get(
            f"/api/v1/analytics/consolidated/chart/?telegram_id={self.TELEGRAM_ID}",
            name="/api/v1/analytics/consolidated/chart/",
        )
