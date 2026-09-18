import logging
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from portfolio.tasks import sync_user_portfolio
from .models import InvestorUser
from .serializers import SetTokenSerializer, TriggerSyncSerializer

logger = logging.getLogger(__name__)


class UserStatusView(APIView):
    """GET /api/v1/users/status/?telegram_id=... — проверка наличия пользователя и токена."""

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
                {"exists": False, "has_token": False, "accounts_count": 0},
                status=status.HTTP_200_OK,
            )

        has_token = bool(user.encrypted_token)
        accounts_count = user.accounts.count()
        return Response(
            {
                "exists": True,
                "has_token": has_token,
                "accounts_count": accounts_count,
            },
            status=status.HTTP_200_OK,
        )


class SetUserTokenView(APIView):
    """POST /api/v1/users/token/ — сохранение токена и запуск синхронизации."""

    def post(self, request):
        serializer = SetTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        tg_id = serializer.validated_data["telegram_id"]
        raw_token = serializer.validated_data["token"]

        user, created = InvestorUser.objects.get_or_create(telegram_id=tg_id)
        user.set_token(raw_token)
        user.save()

        logger.info(f"Токен для пользователя telegram_id={tg_id} успешно зашифрован и сохранен.")

        # Сразу триггерим фоновую задачу сбора портфеля для этого пользователя
        sync_user_portfolio.delay(user.id)

        return Response(
            {
                "status": "ok",
                "message": "Токен успешно сохранен, синхронизация запущена.",
                "created": created,
            },
            status=status.HTTP_200_OK,
        )


class TriggerSyncView(APIView):
    """POST /api/v1/users/sync/ — принудительный триггер синхронизации портфеля."""

    def post(self, request):
        serializer = TriggerSyncSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        tg_id = serializer.validated_data["telegram_id"]
        user = InvestorUser.objects.filter(telegram_id=tg_id).first()

        if not user or not user.encrypted_token:
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
