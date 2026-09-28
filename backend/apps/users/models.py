from cryptography.fernet import Fernet
from django.conf import settings
from django.db import models

# Create your models here.

class InvestorUser(models.Model):

    telegram_id = models.BigIntegerField(
        unique=True,
        db_index=True,
        verbose_name="Telegram ID",
    )

    user_hash = models.CharField(
        max_length=64,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Хэш пользователя (Zero-Knowledge ID)",
        help_text="HMAC-SHA256 от telegram_id с секретной солью для анонимизации",
    )

    encrypted_token = models.CharField(max_length=512, blank=True, default="")

    active_account = models.ForeignKey(
        "portfolio.Account",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    USER_TYPE_RETAIL = "retail"
    USER_TYPE_PRO = "pro"
    USER_TYPE_CHOICES = [
        (USER_TYPE_RETAIL, "Частный инвестор"),
        (USER_TYPE_PRO, "Бизнес / Профессионал"),
    ]

    user_type = models.CharField(
        max_length=20,
        choices=USER_TYPE_CHOICES,
        default=USER_TYPE_RETAIL,
        verbose_name="Тип инвестора",
        help_text="retail - частный инвестор, pro - бизнес / профессиональный инвестор",
    )

    alerts_enabled = models.BooleanField(
        default=True,
        verbose_name="Включены ли риск-алерты",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def set_token(self, raw_token: str) -> None:
        cipher = self._get_cipher()
        encrypted_bytes = cipher.encrypt(raw_token.encode("utf-8"))
        self.encrypted_token = encrypted_bytes.decode("utf-8")

    @property
    def active_broker_token(self):
        return self.broker_tokens.filter(is_active=True).first()

    @property
    def decrypted_token(self) -> str:
        active = self.active_broker_token
        if active and active.encrypted_token:
            return active.decrypted_token
        if self.encrypted_token:
            cipher = self._get_cipher()
            decrypted_bytes = cipher.decrypt(self.encrypted_token.encode("utf-8"))
            return decrypted_bytes.decode("utf-8")
        return ""

    def _get_cipher(self) -> Fernet:
        return Fernet(settings.ENCRYPTION_KEY.encode("utf-8"))

    def save(self, *args, **kwargs):
        if not self.user_hash and self.telegram_id:
            from .security import compute_user_hash
            self.user_hash = compute_user_hash(self.telegram_id)
        super().save(*args, **kwargs)

    @classmethod
    def get_by_id_or_hash(cls, identifier: int | str):
        """
        Универсальный поиск инвестора:
        - По числовому telegram_id (вычисляет хэш и ищет)
        - По 64-символьному user_hash (Zero-Knowledge)
        """
        if not identifier:
            return None
        s_id = str(identifier).strip()
        if s_id.isdigit():
            tg_id = int(s_id)
            from .security import compute_user_hash
            h = compute_user_hash(tg_id)
            user = cls.objects.filter(user_hash=h).first()
            if user:
                return user
            return cls.objects.filter(telegram_id=tg_id).first()
        return cls.objects.filter(user_hash=s_id).first()

    def __str__(self):
        masked_id = f"#{self.telegram_id}" if self.telegram_id else f"hash:{self.user_hash[:8]}..."
        return f"Investor {masked_id}"


class BrokerToken(models.Model):
    user = models.ForeignKey(
        InvestorUser,
        on_delete=models.CASCADE,
        related_name="broker_tokens",
    )
    name = models.CharField(max_length=64, default="Основной токен")
    encrypted_token = models.CharField(max_length=512)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def set_token(self, raw_token: str) -> None:
        cipher = self._get_cipher()
        encrypted_bytes = cipher.encrypt(raw_token.encode("utf-8"))
        self.encrypted_token = encrypted_bytes.decode("utf-8")

    @property
    def decrypted_token(self) -> str:
        if not self.encrypted_token:
            return ""
        cipher = self._get_cipher()
        decrypted_bytes = cipher.decrypt(self.encrypted_token.encode("utf-8"))
        return decrypted_bytes.decode("utf-8")

    def _get_cipher(self) -> Fernet:
        return Fernet(settings.ENCRYPTION_KEY.encode("utf-8"))

    def __str__(self):
        status = "Active" if self.is_active else "Inactive"
        return f"{self.name} ({self.user.telegram_id}) [{status}]"

