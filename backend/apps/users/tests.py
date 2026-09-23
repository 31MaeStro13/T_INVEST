from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from users.models import InvestorUser, BrokerToken


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
