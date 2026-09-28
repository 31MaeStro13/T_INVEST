from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
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
        identifier = request.query_params.get("user_hash") or request.query_params.get("telegram_id")
        if not identifier:
            return Response({"detail": "telegram_id или user_hash обязателен"}, status=400)

        user = InvestorUser.get_by_id_or_hash(identifier)
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
        identifier = (
            request.data.get("user_hash")
            or request.data.get("telegram_id")
            or request.query_params.get("user_hash")
            or request.query_params.get("telegram_id")
        )
        if not identifier:
            return Response({"detail": "telegram_id или user_hash обязателен"}, status=400)

        user = InvestorUser.get_by_id_or_hash(identifier)
        if not user:
            return Response({"detail": "Пользователь не найден"}, status=404)

        user.active_account = None
        user.save(update_fields=["active_account"])
        return Response({
            "status": "ok",
            "active_account_id": None,
            "account_name": "Все счета Т-Банка",
        })


class UploadReportView(APIView):
    """
    POST /api/v1/portfolio/upload_report/
    In-Memory анализ брокерского отчёта Excel (.xlsx).
    Zero-Disk Footprint: на диск не пишется ни байта.

    Защита:
    - Лимит 5 МБ (Nginx + Django)
    - Проверка магического байта ZIP до парсинга
    - Санация ячеек от Formula Injection внутри парсера
    - Лимит строк (10 000) и позиций (500) внутри парсера
    """

    parser_classes = [MultiPartParser, FormParser]

    # Лимит на уровне Django (дублирует Nginx — defence in depth)
    _MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 МБ

    def post(self, request):
        file_obj = request.FILES.get("file")
        if not file_obj:
            return Response(
                {"detail": "Файл отчёта не прикреплён. Загрузите файл с полем 'file'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Проверка расширения (первый барьер — простой)
        if not file_obj.name.lower().endswith(".xlsx"):
            return Response(
                {"detail": "Поддерживаются только отчёты в формате Excel (.xlsx)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Проверка размера до чтения в память
        if file_obj.size > self._MAX_UPLOAD_BYTES:
            return Response(
                {"detail": f"Размер файла превышает лимит {self._MAX_UPLOAD_BYTES // (1024 * 1024)} МБ."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            from .excel_parser import parse_broker_report_xlsx

            # Читаем один раз — парсер сам проверит magic bytes и ZIP структуру
            file_bytes = file_obj.read(self._MAX_UPLOAD_BYTES + 1)
            if len(file_bytes) > self._MAX_UPLOAD_BYTES:
                return Response(
                    {"detail": f"Размер файла превышает лимит {self._MAX_UPLOAD_BYTES // (1024 * 1024)} МБ."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            report_data = parse_broker_report_xlsx(file_bytes)
            return Response(report_data, status=status.HTTP_200_OK)

        except ValueError as err:
            return Response({"detail": str(err)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return Response(
                {"detail": f"Ошибка обработки файла: {exc}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class DBStatsView(APIView):
    """
    GET /api/v1/portfolio/db_stats/
    Возвращает статистику объёма таблиц снимков и позиций.
    Полезно для мониторинга эффекта прореживания (Блок 2).
    """

    def get(self, request):
        from .models import PortfolioSnapshot, Position

        snapshot_count = PortfolioSnapshot.objects.count()
        position_count = Position.objects.count()
        account_count = Account.objects.count()

        pruned_count = PortfolioSnapshot.objects.filter(positions_pruned=True).count()
        not_pruned = snapshot_count - pruned_count

        return Response({
            "accounts": account_count,
            "snapshots": {
                "total": snapshot_count,
                "positions_pruned": pruned_count,
                "positions_intact": not_pruned,
            },
            "positions": position_count,
            "avg_positions_per_snapshot": (
                round(position_count / snapshot_count, 1) if snapshot_count else 0
            ),
        })
