from rest_framework import serializers
from .models import BrokerToken


class BrokerTokenSerializer(serializers.ModelSerializer):
    accounts_count = serializers.SerializerMethodField()

    class Meta:
        model = BrokerToken
        fields = ["id", "name", "is_active", "accounts_count", "created_at"]

    def get_accounts_count(self, obj) -> int:
        return obj.accounts.count()


class SetTokenSerializer(serializers.Serializer):
    telegram_id = serializers.IntegerField(required=True)
    token = serializers.CharField(required=True, max_length=512)
    name = serializers.CharField(required=False, max_length=64, default="Основной токен")

    def validate_token(self, value: str) -> str:
        cleaned = value.strip()
        if not cleaned.startswith("t."):
            raise serializers.ValidationError("Токен Т-Банка должен начинаться на 't.'")
        return cleaned


class TriggerSyncSerializer(serializers.Serializer):
    telegram_id = serializers.IntegerField(required=True)


class SetActiveAccountSerializer(serializers.Serializer):
    telegram_id = serializers.IntegerField(required=True)
    account_id = serializers.IntegerField(required=True)
