from rest_framework import serializers


class SetTokenSerializer(serializers.Serializer):
    telegram_id = serializers.IntegerField(required=True)
    token = serializers.CharField(required=True, max_length=512)

    def validate_token(self, value: str) -> str:
        cleaned = value.strip()
        if not cleaned.startswith("t."):
            raise serializers.ValidationError("Токен Т-Банка должен начинаться на 't.'")
        return cleaned


class TriggerSyncSerializer(serializers.Serializer):
    telegram_id = serializers.IntegerField(required=True)
