from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from users.models import InvestorUser
from .service import get_analytics_for_account, get_consolidated_analytics
from django.http import HttpResponse
from .service import get_chart_for_account, get_consolidated_chart


class ConsolidatedAnalyticsView(APIView):
    """
    GET /api/v1/analytics/consolidated/?telegram_id=...
    """

    def get(self, request):
        tg_id = request.query_params.get("telegram_id")
        if not tg_id or not str(tg_id).isdigit():
            return Response({"detail": "telegram_id обязателен."}, status=status.HTTP_400_BAD_REQUEST)

        user = InvestorUser.objects.filter(telegram_id=int(tg_id)).first()
        if not user:
            return Response({"detail": "Пользователь не найден."}, status=status.HTTP_404_NOT_FOUND)

        try:
            days = int(request.query_params.get("days", 90))
            risk_free_rate = float(request.query_params.get("risk_free_rate", 0.19))
        except (ValueError, TypeError):
            return Response({"detail": "Некорректные параметры запроса."}, status=status.HTTP_400_BAD_REQUEST)

        data = get_consolidated_analytics(user, days=days, risk_free_rate=risk_free_rate)
        if data is None:
            return Response({"detail": "Счета или снимки не найдены."}, status=status.HTTP_404_NOT_FOUND)

        return Response(data)


class AccountAnalyticsView(APIView):
    """
    GET /api/v1/analytics/{account_id}/
    Query params:
        days           — глубина истории (по умолчанию 90)
        risk_free_rate — безрисковая ставка 0..1 (по умолчанию 0.19 = 19%)
    """

    def get(self, request, account_id: int):
        try:
            days = int(request.query_params.get("days", 90))
            risk_free_rate = float(request.query_params.get("risk_free_rate", 0.19))
        except (ValueError, TypeError):
            return Response({"detail": "Некорректные параметры запроса."}, status=status.HTTP_400_BAD_REQUEST)

        data = get_analytics_for_account(account_id, days=days, risk_free_rate=risk_free_rate)

        if data is None:
            return Response({"detail": "Счёт не найден."}, status=status.HTTP_404_NOT_FOUND)

        return Response(data)


class AccountChartView(APIView):
    """
    GET /api/v1/analytics/{account_id}/chart/
    Возвращает PNG-график дашборда для счета.
    """
    def get(self, request, account_id: int):
        chart_bytes = get_chart_for_account(account_id)
        if not chart_bytes:
            return Response({"detail": "Счёт или данные не найдены."}, status=status.HTTP_404_NOT_FOUND)
        return HttpResponse(chart_bytes, content_type="image/png")


class ConsolidatedChartView(APIView):
    """
    GET /api/v1/analytics/consolidated/chart/?telegram_id=...
    Возвращает сводный PNG-график по всем счетам пользователя.
    """
    def get(self, request):
        tg_id = request.query_params.get("telegram_id")
        if not tg_id or not str(tg_id).isdigit():
            return Response({"detail": "telegram_id обязателен."}, status=status.HTTP_400_BAD_REQUEST)
        user = InvestorUser.objects.filter(telegram_id=int(tg_id)).first()
        if not user:
            return Response({"detail": "Пользователь не найден."}, status=status.HTTP_404_NOT_FOUND)
        chart_bytes = get_consolidated_chart(user)
        if not chart_bytes:
            return Response({"detail": "Данные не найдены."}, status=status.HTTP_404_NOT_FOUND)
        return HttpResponse(chart_bytes, content_type="image/png")
