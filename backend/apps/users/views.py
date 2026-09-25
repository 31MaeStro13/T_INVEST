import logging
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from portfolio.tasks import sync_user_portfolio
from .models import InvestorUser, BrokerToken
from .serializers import (
    SetTokenSerializer,
    TriggerSyncSerializer,
    BrokerTokenSerializer,
    SetActiveAccountSerializer,
)

logger = logging.getLogger(__name__)


class UserStatusView(APIView):
    """GET /api/v1/users/status/?telegram_id=... — проверка статуса пользователя."""

    def get(self, request):
        tg_id = request.query_params.get("telegram_id")
        if not tg_id or not str(tg_id).isdigit():
            return Response(
                {"detail": "Некорректный или отсутствующий telegram_id"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = InvestorUser.objects.filter(telegram_id=int(tg_id)).first()
        if not user:
            return Response(
                {
                    "exists": False,
                    "has_token": False,
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


class ToggleAlertsView(APIView):
    """POST /api/v1/users/toggle_alerts/ — переключение статуса риск-алертов."""

    def post(self, request):
        tg_id = request.data.get("telegram_id")
        if not tg_id or not str(tg_id).isdigit():
            return Response(
                {"detail": "telegram_id обязателен и должен быть числом"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = InvestorUser.objects.filter(telegram_id=int(tg_id)).first()
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
    GET /api/v1/tokens/?telegram_id=... — список токенов пользователя
    POST /api/v1/tokens/ — добавление нового токена
    """

    def get(self, request):
        tg_id = request.query_params.get("telegram_id")
        if not tg_id or not str(tg_id).isdigit():
            return Response({"detail": "telegram_id обязателен"}, status=status.HTTP_400_BAD_REQUEST)

        user = InvestorUser.objects.filter(telegram_id=int(tg_id)).first()
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
        tg_id = request.data.get("telegram_id")
        if not tg_id or not str(tg_id).isdigit():
            return Response({"detail": "telegram_id обязателен"}, status=status.HTTP_400_BAD_REQUEST)

        user = InvestorUser.objects.filter(telegram_id=int(tg_id)).first()
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

        tg_id = serializer.validated_data["telegram_id"]
        user = InvestorUser.objects.filter(telegram_id=tg_id).first()

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
