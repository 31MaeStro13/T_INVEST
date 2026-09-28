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


