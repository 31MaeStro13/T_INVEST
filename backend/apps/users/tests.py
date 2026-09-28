from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from users.models import BrokerToken, InvestorUser


class UserModelSecurityTests(TestCase):
    """Тестирование симметричного Fernet-шифрования токенов Т-Банка."""

    def test_fernet_token_encryption_and_decryption(self):
        raw_token = "t.secret_test_token_12345"
        user = InvestorUser.objects.create(telegram_id=999888777)
        user.set_token(raw_token)
        user.save()

        # Токен в базе зашифрован и не равен сырой строке
        self.assertNotEqual(user.encrypted_token, raw_token)
        self.assertTrue(len(user.encrypted_token) > 30)

        # Расшифрованный токен совпадает с исходным
        self.assertEqual(user.decrypted_token, raw_token)

    def test_multi_broker_token_management(self):
        user = InvestorUser.objects.create(telegram_id=111222333)
        tok1 = BrokerToken.objects.create(user=user, name="Токен 1", is_active=True)
        tok1.set_token("t.token_one")
        tok1.save()

        tok2 = BrokerToken.objects.create(user=user, name="Токен 2", is_active=False)
        tok2.set_token("t.token_two")
        tok2.save()

        # Активный токен
        self.assertEqual(user.active_broker_token, tok1)
        self.assertEqual(user.decrypted_token, "t.token_one")

        # Переключение активного токена
        tok1.is_active = False
        tok1.save()
        tok2.is_active = True
        tok2.save()

        user.refresh_from_db()
        self.assertEqual(user.active_broker_token, tok2)
        self.assertEqual(user.decrypted_token, "t.token_two")


class UserApiTests(TestCase):
    """Тестирование API эндпоинтов пользователей."""

    def setUp(self):
        self.client = APIClient()

    def test_user_status_unregistered(self):
        response = self.client.get("/api/v1/users/status/?telegram_id=40404040")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["exists"])
        self.assertFalse(response.data["has_token"])

    def test_user_status_registered_with_token(self):
        user = InvestorUser.objects.create(telegram_id=555666777)
        tok = BrokerToken.objects.create(user=user, name="Основной", is_active=True)
        tok.set_token("t.active_tok")
        tok.save()

        response = self.client.get(f"/api/v1/users/status/?telegram_id={user.telegram_id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["exists"])
        self.assertTrue(response.data["has_token"])
        self.assertEqual(response.data["active_token_name"], "Основной")
        self.assertEqual(response.data["user_type"], "retail")

    def test_set_user_type_toggle(self):
        """Проверка переключения роли (retail -> pro -> retail)."""
        user = InvestorUser.objects.create(telegram_id=12345678)
        self.assertEqual(user.user_type, "retail")

        # Переключаем retail -> pro
        res1 = self.client.post("/api/v1/users/set_type/", {"telegram_id": 12345678}, format="json")
        self.assertEqual(res1.status_code, status.HTTP_200_OK)
        self.assertEqual(res1.data["user_type"], "pro")
        user.refresh_from_db()
        self.assertEqual(user.user_type, "pro")

        # Переключаем pro -> retail
        res2 = self.client.post("/api/v1/users/set_type/", {"telegram_id": 12345678}, format="json")
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertEqual(res2.data["user_type"], "retail")
        user.refresh_from_db()
        self.assertEqual(user.user_type, "retail")

    def test_user_hash_generation_and_lookup(self):
        """Проверка генерации Zero-Knowledge user_hash и поиска get_by_id_or_hash."""
        user = InvestorUser.objects.create(telegram_id=777888999)
        self.assertIsNotNone(user.user_hash)
        self.assertEqual(len(user.user_hash), 64)

        # Поиск по raw telegram_id
        found_by_tg = InvestorUser.get_by_id_or_hash(777888999)
        self.assertEqual(found_by_tg, user)

        # Поиск по 64-символьному user_hash
        found_by_hash = InvestorUser.get_by_id_or_hash(user.user_hash)
        self.assertEqual(found_by_hash, user)

    def test_user_status_by_user_hash(self):
        """Проверка получения статуса по user_hash."""
        user = InvestorUser.objects.create(telegram_id=333444555)
        response = self.client.get(f"/api/v1/users/status/?user_hash={user.user_hash}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["exists"])
        self.assertEqual(response.data["user_hash"], user.user_hash)

    def test_delete_account_gdpr_cascading(self):
        """Проверка каскадного удаления всех данных инвестора (152-ФЗ / GDPR)."""
        from portfolio.models import Account, PortfolioSnapshot, Position

        user = InvestorUser.objects.create(telegram_id=444555666)
        token = BrokerToken.objects.create(user=user, name="Удаляемый токен")
        token.set_token("t.delete_me")
        token.save()

        account = Account.objects.create(investor=user, broker_token=token, account_id="acc_del_1", name="Счет")
        snap = PortfolioSnapshot.objects.create(account=account, total_amount_portfolio=100000)
        pos = Position.objects.create(
            snapshot=snap,
            figi="BBG000B9XRY4",
            ticker="AAPL",
            instrument_type="share",
            quantity=10,
            current_price=150.0,
            expected_yield=20.0,
        )

        # Удаляем аккаунт через API


        response = self.client.post("/api/v1/users/delete_account/", {"telegram_id": 444555666}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "ok")

        # Проверяем каскадное удаление всех связанных сущностей
        self.assertFalse(InvestorUser.objects.filter(id=user.id).exists())
        self.assertFalse(BrokerToken.objects.filter(id=token.id).exists())
        self.assertFalse(Account.objects.filter(id=account.id).exists())
        self.assertFalse(PortfolioSnapshot.objects.filter(id=snap.id).exists())
        self.assertFalse(Position.objects.filter(id=pos.id).exists())

    def test_delete_account_by_user_hash(self):
        """Проверка удаления аккаунта по Zero-Knowledge user_hash."""
        user = InvestorUser.objects.create(telegram_id=888999111)
        u_hash = user.user_hash

        response = self.client.delete(f"/api/v1/users/delete_account/?user_hash={u_hash}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(InvestorUser.objects.filter(telegram_id=888999111).exists())

    def test_delete_account_not_found(self):
        """Проверка попытки удаления несуществующего аккаунта."""
        response = self.client.post("/api/v1/users/delete_account/", {"telegram_id": 999999999}, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

