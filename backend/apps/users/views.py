import logging

from django.core.cache import cache
from portfolio.tasks import sync_user_portfolio
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import BrokerToken, InvestorUser
from .security import mask_identifier
from .serializers import (
    BrokerTokenSerializer,
    DeleteAccountSerializer,
    SetTokenSerializer,
    TriggerSyncSerializer,
)

logger = logging.getLogger(__name__)



class UserStatusView(APIView):
    """GET /api/v1/users/status/?telegram_id=... или ?user_hash=... — проверка статуса пользователя."""

    def get(self, request):
        user_hash = request.query_params.get("user_hash")
        tg_id = request.query_params.get("telegram_id")
        identifier = user_hash or tg_id

        if not identifier:
            return Response(
                {"detail": "Некорректный или отсутствующий identifier (telegram_id или user_hash)"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = InvestorUser.get_by_id_or_hash(identifier)
        if not user:
            return Response(
                {
                    "exists": False,
                    "has_token": False,
                    "user_hash": None,
                    "user_type": "retail",
                    "user_type_display": "Частный инвестор",
                    "accounts_count": 0,
                    "active_account_id": None,
                    "active_account_name": None,
                    "active_token_name": None,
                    "tokens_count": 0,
                    "alerts_enabled": True,
                },
                status=status.HTTP_200_OK,
            )

        active_tok = user.active_broker_token
        has_token = bool(active_tok or user.encrypted_token)
        active_acc = user.active_account

        return Response(
            {
                "exists": True,
                "has_token": has_token,
                "user_hash": user.user_hash,
                "user_type": user.user_type,
                "user_type_display": user.get_user_type_display(),
                "accounts_count": user.accounts.count(),
                "active_account_id": active_acc.id if active_acc else None,
                "active_account_name": active_acc.name if active_acc else None,
                "active_token_id": active_tok.id if active_tok else None,
                "active_token_name": active_tok.name if active_tok else None,
                "tokens_count": user.broker_tokens.count(),
                "alerts_enabled": user.alerts_enabled,
            },
            status=status.HTTP_200_OK,
        )


class SetUserTypeView(APIView):
    """POST /api/v1/users/set_type/ — переключение роли инвестора (retail / pro)."""

    def post(self, request):
        identifier = request.data.get("user_hash") or request.data.get("telegram_id")
        user_type = request.data.get("user_type")

        if not identifier:
            return Response(
                {"detail": "Параметр telegram_id или user_hash обязателен"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = InvestorUser.get_by_id_or_hash(identifier)
        if not user:
            return Response(
                {"detail": "Пользователь не найден"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if user_type:
            if user_type not in (InvestorUser.USER_TYPE_RETAIL, InvestorUser.USER_TYPE_PRO):
                return Response(
                    {
                        "detail": f"Недопустимый user_type. Разрешены: {InvestorUser.USER_TYPE_RETAIL}, {InvestorUser.USER_TYPE_PRO}"
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            user.user_type = user_type
        else:
            user.user_type = (
                InvestorUser.USER_TYPE_PRO
                if user.user_type == InvestorUser.USER_TYPE_RETAIL
                else InvestorUser.USER_TYPE_RETAIL
            )

        user.save(update_fields=["user_type"])
        logger.info(f"Инвестор {user.user_hash[:8] if user.user_hash else user.telegram_id} сменил роль на {user.user_type}")

        return Response(
            {
                "status": "ok",
                "telegram_id": user.telegram_id,
                "user_hash": user.user_hash,
                "user_type": user.user_type,
                "user_type_display": user.get_user_type_display(),
            },
            status=status.HTTP_200_OK,
        )


class ToggleAlertsView(APIView):
    """POST /api/v1/users/toggle_alerts/ — переключение статуса риск-алертов."""

    def post(self, request):
        identifier = request.data.get("user_hash") or request.data.get("telegram_id")
        if not identifier:
            return Response(
                {"detail": "telegram_id или user_hash обязателен"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = InvestorUser.get_by_id_or_hash(identifier)
        if not user:
            return Response({"detail": "Пользователь не найден"}, status=status.HTTP_404_NOT_FOUND)

        user.alerts_enabled = not user.alerts_enabled
        user.save(update_fields=["alerts_enabled"])

        return Response(
            {"alerts_enabled": user.alerts_enabled},
            status=status.HTTP_200_OK,
        )



class SetUserTokenView(APIView):
    """POST /api/v1/users/token/ — сохранение токена и запуск синхронизации."""

    def post(self, request):
        serializer = SetTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        tg_id = serializer.validated_data["telegram_id"]
        raw_token = serializer.validated_data["token"]
        token_name = serializer.validated_data.get("name") or "Основной портфель"

        user, created = InvestorUser.objects.get_or_create(telegram_id=tg_id)

        # Деактивируем предыдущие токены пользователя
        user.broker_tokens.update(is_active=False)

        # Создаем новый токен как активный
        broker_token = BrokerToken.objects.create(
            user=user,
            name=token_name,
            is_active=True,
        )
        broker_token.set_token(raw_token)
        broker_token.save()

        # Дублируем для обратной совместимости
        user.set_token(raw_token)
        user.save()

        logger.info(f"Токен '{token_name}' для telegram_id={tg_id} успешно сохранен.")

        # Сразу триггерим фоновую задачу сбора портфеля
        sync_user_portfolio.delay(user.id)

        return Response(
            {
                "status": "ok",
                "message": f"Токен '{token_name}' успешно сохранен, синхронизация запущена.",
                "token_id": broker_token.id,
                "token_name": broker_token.name,
                "created": created,
            },
            status=status.HTTP_200_OK,
        )


class TokensListView(APIView):
    """
    GET /api/v1/tokens/?telegram_id=... или ?user_hash=... — список токенов пользователя
    POST /api/v1/tokens/ — добавление нового токена
    """

    def get(self, request):
        identifier = request.query_params.get("user_hash") or request.query_params.get("telegram_id")
        if not identifier:
            return Response({"detail": "telegram_id или user_hash обязателен"}, status=status.HTTP_400_BAD_REQUEST)

        user = InvestorUser.get_by_id_or_hash(identifier)
        if not user:
            return Response([], status=status.HTTP_200_OK)

        tokens = user.broker_tokens.order_by("-is_active", "-created_at")
        serializer = BrokerTokenSerializer(tokens, many=True)
        return Response(serializer.data)

    def post(self, request):
        return SetUserTokenView().post(request)


class ActivateTokenView(APIView):
    """POST /api/v1/tokens/<int:token_id>/activate/ — сделать токен активным."""

    def post(self, request, token_id: int):
        identifier = request.data.get("user_hash") or request.data.get("telegram_id")
        if not identifier:
            return Response({"detail": "telegram_id или user_hash обязателен"}, status=status.HTTP_400_BAD_REQUEST)

        user = InvestorUser.get_by_id_or_hash(identifier)
        if not user:
            return Response({"detail": "Пользователь не найден"}, status=status.HTTP_404_NOT_FOUND)

        try:
            target_token = user.broker_tokens.get(id=token_id)
        except BrokerToken.DoesNotExist:
            return Response({"detail": "Токен не найден"}, status=status.HTTP_404_NOT_FOUND)

        # Переключаем активность
        user.broker_tokens.update(is_active=False)
        target_token.is_active = True
        target_token.save(update_fields=["is_active"])

        # Обновляем активный счет на лучший счет из этого токена
        best_acc = target_token.accounts.order_by("-snapshots__total_amount_portfolio").first()
        if best_acc:
            user.active_account = best_acc
            user.save(update_fields=["active_account"])

        # Запускаем актуализацию данных
        sync_user_portfolio.delay(user.id)

        return Response({
            "status": "ok",
            "active_token_id": target_token.id,
            "active_token_name": target_token.name,
            "active_account_id": user.active_account_id,
        })


class TriggerSyncView(APIView):
    """POST /api/v1/users/sync/ — принудительный триггер синхронизации портфеля."""

    def post(self, request):
        serializer = TriggerSyncSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        tg_id = serializer.validated_data.get("telegram_id")
        user_hash = serializer.validated_data.get("user_hash")
        identifier = user_hash or tg_id

        user = InvestorUser.get_by_id_or_hash(identifier)

        if not user or (not user.encrypted_token and not user.broker_tokens.exists()):
            return Response(
                {"detail": "Пользователь не найден или токен не привязан"},
                status=status.HTTP_404_NOT_FOUND,
            )

        sync_user_portfolio.delay(user.id)
        logger.info(f"Ручная синхронизация поставлена в очередь для user_id={user.id}")

        return Response(
            {"status": "ok", "message": "Синхронизация успешно поставлена в очередь."},
            status=status.HTTP_200_OK,
        )


class DeleteAccountView(APIView):
    """
    POST / DELETE /api/v1/users/delete_account/
    Право на забвение (152-ФЗ / GDPR Article 17 Right to be Forgotten).
    Безвозвратно удаляет пользователя, все токены, счета, снимки, позиции и кэш Redis.
    """

    def _delete_user_data(self, identifier):
        if not identifier:
            return Response(
                {"detail": "Параметр telegram_id или user_hash обязателен"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = InvestorUser.get_by_id_or_hash(identifier)
        if not user:
            return Response({"detail": "Пользователь не найден"}, status=status.HTTP_404_NOT_FOUND)

        user_id = user.id
        user_hash = user.user_hash or ""
        account_ids = list(user.accounts.values_list("id", flat=True))

        # Очистка кэша Redis для пользователя и его счетов
        cache.delete(f"chart:consolidated:{user_id}")
        cache.delete(f"snapshot:consolidated:{user_id}:all")
        for acc_id in account_ids:
            cache.delete(f"chart:account:{acc_id}")
            for d in (30, 90, 180, 365):
                cache.delete(f"analytics:account:{acc_id}:{d}")

        for d in (30, 90, 180, 365):
            cache.delete(f"analytics:consolidated:{user_id}:all:{d}")
            if user.active_broker_token:
                cache.delete(f"analytics:consolidated:{user_id}:{user.active_broker_token.id}:{d}")
                cache.delete(f"snapshot:consolidated:{user_id}:{user.active_broker_token.id}")

        # Каскадное удаление инвестора (tokens, accounts, snapshots, positions)
        user.delete()
        masked = mask_identifier(user_hash or identifier)
        logger.info(f"Инвестор {masked} удалил аккаунт (Право на забвение 152-ФЗ / GDPR)")

        return Response(
            {
                "status": "ok",
                "message": "Все данные пользователя, токены, счета и история успешно и безвозвратно удалены.",
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        serializer = DeleteAccountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        identifier = serializer.validated_data.get("user_hash") or serializer.validated_data.get("telegram_id")
        return self._delete_user_data(identifier)

    def delete(self, request):
        identifier = (
            request.data.get("user_hash")
            or request.data.get("telegram_id")
            or request.query_params.get("user_hash")
            or request.query_params.get("telegram_id")
        )
        return self._delete_user_data(identifier)

