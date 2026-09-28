import io
from decimal import Decimal

import openpyxl
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient
from users.models import BrokerToken, InvestorUser

from portfolio.models import Account, PortfolioSnapshot, Position
from portfolio.services import get_consolidated_snapshot


class ConsolidatedPortfolioTests(TestCase):
    """Тестирование консолидации счетов и склеивания позиций."""

    def setUp(self):
        self.user = InvestorUser.objects.create(telegram_id=888777666)
        self.token = BrokerToken.objects.create(user=self.user, name="Основной", is_active=True)

        # Счет 1: ИИС
        self.acc1 = Account.objects.create(
            investor=self.user,
            broker_token=self.token,
            account_id="acc_1",
            name="ИИС",
        )
        snap1 = PortfolioSnapshot.objects.create(
            account=self.acc1,
            total_amount_portfolio=Decimal("50000.00"),
            total_amount_shares=Decimal("40000.00"),
            total_amount_bonds=Decimal("0.00"),
            total_amount_etf=Decimal("10000.00"),
            total_amount_currencies=Decimal("0.00"),
            expected_yield=Decimal("1500.00"),
        )
        Position.objects.create(
            snapshot=snap1,
            figi="FIGI_SBER",
            ticker="SBER",
            name="Сбербанк",
            instrument_type="share",
            quantity=Decimal("100.00"),
            current_price=Decimal("300.00"),
            average_position_price=Decimal("285.00"),
            expected_yield=Decimal("1500.00"),
        )

        # Счет 2: Брокерский
        self.acc2 = Account.objects.create(
            investor=self.user,
            broker_token=self.token,
            account_id="acc_2",
            name="Брокерский",
        )
        snap2 = PortfolioSnapshot.objects.create(
            account=self.acc2,
            total_amount_portfolio=Decimal("25000.00"),
            total_amount_shares=Decimal("15000.00"),
            total_amount_bonds=Decimal("10000.00"),
            total_amount_etf=Decimal("0.00"),
            total_amount_currencies=Decimal("0.00"),
            expected_yield=Decimal("-500.00"),
        )
        # Пересекающаяся бумага SBER на втором счете
        Position.objects.create(
            snapshot=snap2,
            figi="FIGI_SBER",
            ticker="SBER",
            name="Сбербанк",
            instrument_type="share",
            quantity=Decimal("50.00"),
            current_price=Decimal("300.00"),
            average_position_price=Decimal("310.00"),
            expected_yield=Decimal("-500.00"),
        )

    def test_consolidated_snapshot_aggregation(self):
        """Проверка склеивания балансов и повторяющихся позиций."""
        res = get_consolidated_snapshot(self.user)
        self.assertIsNotNone(res)

        # Суммарный баланс 50000 + 25000 = 75000
        self.assertEqual(Decimal(res["total_amount_portfolio"]), Decimal("75000.00"))
        self.assertEqual(Decimal(res["total_amount_shares"]), Decimal("55000.00"))
        self.assertEqual(Decimal(res["total_amount_bonds"]), Decimal("10000.00"))
        self.assertEqual(Decimal(res["total_amount_etf"]), Decimal("10000.00"))
        self.assertEqual(Decimal(res["expected_yield"]), Decimal("1000.00"))

        # Позиции: SBER должен объединиться в одну строку: 100 + 50 = 150 шт.
        positions = res["positions"]
        self.assertEqual(len(positions), 1)
        sber = positions[0]
        self.assertEqual(sber["ticker"], "SBER")
        self.assertEqual(Decimal(sber["quantity"]), Decimal("150.00"))
        self.assertEqual(Decimal(sber["expected_yield"]), Decimal("1000.00"))

    def test_consolidated_snapshot_api_endpoint(self):
        """Проверка REST эндпоинта /api/v1/accounts/consolidated_snapshot/"""
        client = APIClient()
        response = client.get(f"/api/v1/accounts/consolidated_snapshot/?telegram_id={self.user.telegram_id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["account_name"], "Все счета Т-Банка")
        self.assertEqual(len(response.data["positions"]), 1)

    def test_activate_consolidated_endpoint(self):
        """Проверка переключения в режим 'Все счета'."""
        self.user.active_account = self.acc1
        self.user.save()

        client = APIClient()
        response = client.post(
            "/api/v1/accounts/activate_consolidated/",
            {"telegram_id": self.user.telegram_id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.active_account)


class ExcelBrokerReportParserTests(TestCase):
    """Тестирование In-Memory парсера брокерских отчетов Excel (.xlsx)."""

    def _create_sample_excel(self) -> bytes:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Активы"

        # Заголовки
        ws.append(["Тикер", "Наименование", "Количество", "Текущая цена", "Стоимость", "Тип"])
        # Данные
        ws.append(["SBER", "Сбербанк ПАО", 100, 300.0, 30000.0, "Акции"])
        ws.append(["SU26238RMFS4", "ОФЗ 26238", 20, 1000.0, 20000.0, "Облигации"])
        ws.append(["LQDT", "Ликвидность БПИФ", 500, 1.4, 700.0, "Фонд"])

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return buf.getvalue()

    def test_in_memory_parser_success(self):
        from portfolio.excel_parser import parse_broker_report_xlsx

        excel_bytes = self._create_sample_excel()
        res = parse_broker_report_xlsx(excel_bytes)

        self.assertEqual(res["status"], "success")
        self.assertEqual(res["positions_count"], 3)
        self.assertAlmostEqual(res["total_amount_portfolio"], 50700.0, places=1)

        # Проверка классификации активов
        breakdown = res["asset_breakdown"]
        self.assertAlmostEqual(breakdown["shares"], 30000.0, places=1)
        self.assertAlmostEqual(breakdown["bonds"], 20000.0, places=1)
        self.assertAlmostEqual(breakdown["etf"], 700.0, places=1)

        # Проверка метрик риска (HHI)
        self.assertIn("hhi_index", res["risk_metrics"])
        self.assertIn("concentration_level", res["risk_metrics"])

    def test_upload_report_api_endpoint(self):
        excel_bytes = self._create_sample_excel()
        uploaded = SimpleUploadedFile(
            "broker_report.xlsx",
            excel_bytes,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        client = APIClient()
        response = client.post("/api/v1/portfolio/upload_report/", {"file": uploaded}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "success")
        self.assertEqual(response.data["positions_count"], 3)

    def test_upload_report_invalid_format(self):
        bad_file = SimpleUploadedFile("bad.txt", b"plain text content", content_type="text/plain")
        client = APIClient()
        response = client.post("/api/v1/portfolio/upload_report/", {"file": bad_file}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("detail", response.data)


class DataRetentionTests(TestCase):
    """
    Тестирование Блока 2 — оптимизация и контроль роста БД.
    Покрывает Position Pruning и логику Downsampling (pick_daily / pick_weekly).
    """

    def setUp(self):
        self.user = InvestorUser.objects.create(telegram_id=777000111)
        self.account = Account.objects.create(
            investor=self.user,
            account_id="retention_acc",
            name="Тестовый счёт",
        )

    def _make_snapshot(self, **kwargs) -> PortfolioSnapshot:
        """Вспомогательный метод: создаёт снимок напрямую (минуя save_portfolio_snapshot)."""
        return PortfolioSnapshot.objects.create(account=self.account, **kwargs)

    def _add_positions(self, snapshot: PortfolioSnapshot, count: int = 3):
        """Добавляет <count> позиций к снимку."""
        Position.objects.bulk_create([
            Position(
                snapshot=snapshot,
                figi=f"FIGI{i}",
                ticker=f"TCK{i}",
                instrument_type="share",
                quantity=Decimal("10"),
                current_price=Decimal("100"),
                expected_yield=Decimal("5"),
            )
            for i in range(count)
        ])

    # ── 2.1 Position Pruning ─────────────────────────────────────────────────

    def test_pruning_deletes_old_positions_on_new_snapshot(self):
        """
        После сохранения нового снимка через save_portfolio_snapshot,
        позиции у всех предыдущих снимков должны быть удалены.
        """
        from unittest.mock import MagicMock

        from portfolio.services import save_portfolio_snapshot

        # Создаём первый снимок напрямую с позициями
        snap1 = self._make_snapshot()
        self._add_positions(snap1, count=5)
        self.assertEqual(Position.objects.filter(snapshot=snap1).count(), 5)

        # Мокаем portfolio_data для второго снимка
        pos_mock = MagicMock()
        pos_mock.figi = "FIGI_NEW"
        pos_mock.ticker = "NEW"
        pos_mock.instrument_type = "share"
        pos_mock.quantity.units = 10
        pos_mock.quantity.nano = 0
        pos_mock.current_price.units = 200
        pos_mock.current_price.nano = 0
        pos_mock.average_position_price.units = 190
        pos_mock.average_position_price.nano = 0
        pos_mock.expected_yield.units = 5
        pos_mock.expected_yield.nano = 0

        portfolio_mock = MagicMock()
        portfolio_mock.positions = [pos_mock]
        for field in [
            "total_amount_portfolio", "total_amount_shares", "total_amount_bonds",
            "total_amount_etf", "total_amount_currencies",
        ]:
            attr = getattr(portfolio_mock, field)
            attr.units = 1000
            attr.nano = 0
        portfolio_mock.expected_yield = None

        snap2 = save_portfolio_snapshot(account=self.account, portfolio_data=portfolio_mock)

        # Старый снимок не должен иметь позиций
        self.assertEqual(Position.objects.filter(snapshot=snap1).count(), 0)
        # Новый снимок должен иметь позиции
        self.assertEqual(Position.objects.filter(snapshot=snap2).count(), 1)
        # Флаг positions_pruned у старого снимка должен быть True
        snap1.refresh_from_db()
        self.assertTrue(snap1.positions_pruned)
        # Флаг positions_pruned у нового снимка должен быть False
        self.assertFalse(snap2.positions_pruned)

    def test_pruning_flag_set_on_old_snapshots(self):
        """Снимки без позиций (после pruning) помечаются positions_pruned=True."""
        snap1 = self._make_snapshot()
        snap2 = self._make_snapshot()
        self._add_positions(snap1, count=2)
        self._add_positions(snap2, count=2)

        # Ручной pruning (имитируем логику из services.py)
        Position.objects.filter(
            snapshot__account=self.account
        ).exclude(snapshot_id=snap2.id).delete()
        PortfolioSnapshot.objects.filter(
            account=self.account
        ).exclude(id=snap2.id).update(positions_pruned=True)

        snap1.refresh_from_db()
        snap2.refresh_from_db()
        self.assertTrue(snap1.positions_pruned)
        self.assertFalse(snap2.positions_pruned)

    # ── 2.2 Downsampling helpers ─────────────────────────────────────────────

    def test_pick_daily_keeps_latest_per_day(self):
        """_pick_daily должен оставлять самый поздний снимок за каждый день."""
        import datetime

        from django.utils import timezone

        from portfolio.tasks import _pick_daily

        now = timezone.now()
        day1_morning = now.replace(hour=9, minute=0, second=0)
        day1_evening = now.replace(hour=22, minute=0, second=0)
        day2_noon = (now + datetime.timedelta(days=1)).replace(hour=12, minute=0, second=0)

        snapshots = [(1, day1_morning), (2, day1_evening), (3, day2_noon)]
        keep = _pick_daily(snapshots)

        self.assertIn(2, keep)   # вечерний день1 — оставить
        self.assertIn(3, keep)   # единственный день2 — оставить
        self.assertNotIn(1, keep)  # утренний день1 — удалить

    def test_pick_weekly_keeps_latest_per_week(self):
        """_pick_weekly должен оставлять самый поздний снимок за каждую ISO-неделю."""
        import datetime

        from django.utils import timezone

        from portfolio.tasks import _pick_weekly

        # Неделя 1: понедельник и пятница
        monday = timezone.now().replace(hour=10)
        # Находим ближайший понедельник
        monday = monday - datetime.timedelta(days=monday.weekday())
        friday = monday + datetime.timedelta(days=4)
        # Неделя 2: следующий понедельник
        next_monday = monday + datetime.timedelta(weeks=1)

        snapshots = [(10, monday), (11, friday), (12, next_monday)]
        keep = _pick_weekly(snapshots)

        self.assertIn(11, keep)    # пятница — последняя на первой неделе
        self.assertIn(12, keep)    # единственная на второй неделе
        self.assertNotIn(10, keep)  # понедельник первой недели — удалить

    def test_db_stats_endpoint(self):
        """GET /api/v1/portfolio/db_stats/ возвращает корректную структуру."""
        from rest_framework.test import APIClient
        client = APIClient()
        snap = self._make_snapshot()
        self._add_positions(snap, count=4)

        response = client.get("/api/v1/portfolio/db_stats/")
        self.assertEqual(response.status_code, 200)
        data = response.data
        self.assertIn("accounts", data)
        self.assertIn("snapshots", data)
        self.assertIn("positions", data)
        self.assertGreaterEqual(data["positions"], 4)
        self.assertGreaterEqual(data["snapshots"]["total"], 1)
