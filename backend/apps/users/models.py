from django.db import models
from django.conf import settings
from cryptography.fernet import Fernet

# Create your models here.

class InvestorUser(models.Model):

    telegram_id = models.BigIntegerField(
        unique=True,
        db_index=True,
        verbose_name=("Telegram ID")
    )

    encrypted_token = models.CharField(max_length=512)

    created_at = models.DateTimeField(auto_now_add=True)

    # не я написал функции
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
