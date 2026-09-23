from rest_framework import serializers
from .models import Account, PortfolioSnapshot, Position

class AccountSerializer(serializers.ModelSerializer):
    is_active = serializers.SerializerMethodField()
    latest_balance = serializers.SerializerMethodField()

    class Meta:
        model = Account
        fields = [
            "id", "account_id", "name", "account_type",
            "status", "is_active", "latest_balance", "created_at"
        ]

    def get_is_active(self, obj) -> bool:
        return bool(obj.investor and obj.investor.active_account_id == obj.id)

    def get_latest_balance(self, obj) -> float | None:
        last = obj.snapshots.order_by("-created_at").first()
        return float(last.total_amount_portfolio) if last else None


class PositionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Position
        fields = [
            "id", "figi", "ticker", "name",
            "instrument_type", "quantity",
            "current_price", "expected_yield"
        ]


class PortfolioSnapshotSerializer(serializers.ModelSerializer):

    positions = PositionSerializer(many=True, read_only=True)
    class Meta:
        model = PortfolioSnapshot
        fields = [
            "id",
            "created_at",
            "total_amount_portfolio",
            "total_amount_shares",
            "total_amount_bonds",
            "total_amount_etf",
            "total_amount_currencies",
            "expected_yield",
            "positions",
        ]
