from django.shortcuts import render
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Account
from .serializers import AccountSerializer, PortfolioSnapshotSerializer
# Create your views here.


class AccountViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AccountSerializer

    def get_queryset(self):
        qs = Account.objects.all()
        tg_id = self.request.query_params.get("telegram_id")
        if tg_id and str(tg_id).isdigit():
            qs = qs.filter(investor__telegram_id=int(tg_id))
        return qs

    @action(detail=True, methods=["get"])
    def latest_snapshot(self, request, pk=None):
        account = self.get_object()
        latest = account.snapshots.prefetch_related("positions").order_by("-created_at").first()

        if not latest:
            return Response({"detail": "Снимка нет"}, status=404)

        serializer = PortfolioSnapshotSerializer(latest)
        return Response(serializer.data)
