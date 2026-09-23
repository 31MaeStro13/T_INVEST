from django.db import models
from django.conf import settings
from cryptography.fernet import Fernet

# Create your models here.

class InvestorUser(models.Model):

    telegram_id = models.BigIntegerField(
        unique=True,
        db_index=True,
        verbose_name="Telegram ID",
    )

    encrypted_token = models.CharField(max_length=512, blank=True, default="")

    active_account = models.ForeignKey(
        "portfolio.Account",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
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

    def __str__(self):
        return f"Investor #{self.telegram_id}"


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

