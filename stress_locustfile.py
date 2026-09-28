"""
stress_locustfile.py — Жесткий стресс-тест T-Invest Portfolio Auditor (Шквальный огонь).

Имитирует максимальную пиковую нагрузку без искусственных пауз (wait_time = constant(0)).
Используется для определения точки отказа (breaking point), предельного RPS и насыщения пула соединений.
"""

from locust import HttpUser, task, constant


class StressInvestorUser(HttpUser):
    # Шквальная нагрузка без пауз между запросами
    wait_time = constant(0)

    TELEGRAM_ID = 1531218972
    ACCOUNT_ID = 1

    @task(4)
    def test_accounts_list(self):
        """Список счетов инвестора."""
        self.client.get(
            f"/api/v1/accounts/?telegram_id={self.TELEGRAM_ID}",
            name="/api/v1/accounts/",
        )

    @task(3)
    def test_latest_snapshot(self):
        """Снимок счета (40+ позиций)."""
        self.client.get(
            f"/api/v1/accounts/{self.ACCOUNT_ID}/latest_snapshot/",
            name="/api/v1/accounts/[id]/latest_snapshot/",
        )

    @task(3)
    def test_consolidated_snapshot(self):
        """Сводный портфель (Redis кэш / склейка)."""
        self.client.get(
            f"/api/v1/accounts/consolidated_snapshot/?telegram_id={self.TELEGRAM_ID}",
            name="/api/v1/accounts/consolidated_snapshot/",
        )

    @task(2)
    def test_risk_analytics(self):
        """Риск-метрики NumPy (Redis кэш)."""
        self.client.get(
            f"/api/v1/analytics/consolidated/?telegram_id={self.TELEGRAM_ID}",
            name="/api/v1/analytics/consolidated/",
        )

    @task(1)
    def test_portfolio_chart(self):
        """Аналитический график (Redis кэш)."""
        self.client.get(
            f"/api/v1/analytics/consolidated/chart/?telegram_id={self.TELEGRAM_ID}",
            name="/api/v1/analytics/consolidated/chart/",
        )
