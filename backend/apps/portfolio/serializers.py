from rest_framework import serializers
from .models import Account, PortfolioSnapshot, Position

class AccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = Account
        fields = ["id", "account_id", "name", "account_type", "status", "created_at"]


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
