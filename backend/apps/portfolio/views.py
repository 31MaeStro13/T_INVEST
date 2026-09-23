from django.shortcuts import render
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from users.models import InvestorUser
from .models import Account
from .serializers import AccountSerializer, PortfolioSnapshotSerializer


class AccountViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AccountSerializer

    def get_queryset(self):
        qs = Account.objects.all().select_related("investor")
        tg_id = self.request.query_params.get("telegram_id")
        if tg_id and str(tg_id).isdigit():
            user = InvestorUser.objects.filter(telegram_id=int(tg_id)).first()
            if user:
                active_token = user.active_broker_token
                if active_token and Account.objects.filter(investor=user, broker_token=active_token).exists():
                    qs = qs.filter(investor=user, broker_token=active_token)
                else:
                    qs = qs.filter(investor=user)
        return qs.order_by("id")

    @action(detail=True, methods=["get"])
    def latest_snapshot(self, request, pk=None):
        account = self.get_object()
        latest = account.snapshots.prefetch_related("positions").order_by("-created_at").first()

        if not latest:
            return Response({"detail": "Снимка нет"}, status=404)

        serializer = PortfolioSnapshotSerializer(latest)
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        """Делает этот счет активным (выбранным) для инвестора."""
        account = self.get_object()
        user = account.investor
        user.active_account = account
        user.save(update_fields=["active_account"])
        return Response({
            "status": "ok",
            "active_account_id": account.id,
            "account_name": account.name,
        })

    @action(detail=False, methods=["get"])
    def consolidated_snapshot(self, request):
        """Возвращает агрегированный снимок по всем счетам пользователя."""
        tg_id = request.query_params.get("telegram_id")
        if not tg_id or not str(tg_id).isdigit():
            return Response({"detail": "telegram_id обязателен"}, status=400)

        user = InvestorUser.objects.filter(telegram_id=int(tg_id)).first()
        if not user:
            return Response({"detail": "Пользователь не найден"}, status=404)

        from .services import get_consolidated_snapshot
        data = get_consolidated_snapshot(user)
        if not data:
            return Response({"detail": "Снимки отсутствуют"}, status=404)

        return Response(data)

    @action(detail=False, methods=["post"])
    def activate_consolidated(self, request):
        """Активирует режим 'Все счета' (сбрасывает активный счет в None)."""
        tg_id = request.data.get("telegram_id")
        if not tg_id or not str(tg_id).isdigit():
            return Response({"detail": "telegram_id обязателен"}, status=400)

        user = InvestorUser.objects.filter(telegram_id=int(tg_id)).first()
        if not user:
            return Response({"detail": "Пользователь не найден"}, status=404)

        user.active_account = None
        user.save(update_fields=["active_account"])
        return Response({
            "status": "ok",
            "active_account_id": None,
            "account_name": "Все счета Т-Банка",
        })

