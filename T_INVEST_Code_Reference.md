# 💻 T_INVEST: Пошаговый код проекта и архитектурная шпаргалка

В этом документе собраны все готовые файлы проекта с их реальным кодом, путями и комментариями по шагам реализации.

---

## 📌 Оглавление
1. [Этап 1: Модели данных (users и portfolio)](#этап-1-модели-данных)
2. [Этап 2: Сервисный слой и транзакции (services.py)](#этап-2-сервисный-слой-и-транзакции)
3. [Этап 3: Инфраструктура брокера (Docker + Redis)](#этап-3-инфраструктура-брокера-docker--redis)
4. [Этап 4: Подключение Celery к Django (конфигурация)](#этап-4-подключение-celery-к-django)
5. [Этап 5: Фоновые задачи, ретраи и диспетчер (tasks.py)](#этап-5-фоновые-задачи-ретраи-и-диспетчер)
6. [Этап 6: REST API на Django REST Framework](#этап-6-rest-api-на-django-rest-framework)
7. [Шпаргалка консольных команд](#шпаргалка-консольных-команд-для-запуска)

---

## Этап 1: Модели данных

### 1.1 Модель инвестора с шифрованием Fernet
📁 `backend/apps/users/models.py`

```python
from django.db import models
from django.conf import settings
from cryptography.fernet import Fernet


class InvestorUser(models.Model):
    telegram_id = models.BigIntegerField(
        unique=True,
        db_index=True,
        verbose_name="Telegram ID"
    )
    encrypted_token = models.CharField(max_length=512)
    created_at = models.DateTimeField(auto_now_add=True)

    def set_token(self, raw_token: str) -> None:
        """Симметрично зашифровывает токен Т-Банка ключом из settings.ENCRYPTION_KEY"""
        cipher = self._get_cipher()
        encrypted_bytes = cipher.encrypt(raw_token.encode("utf-8"))
        self.encrypted_token = encrypted_bytes.decode("utf-8")

    @property
    def decrypted_token(self) -> str:
        """Расшифровывает токен на лету для запроса в API"""
        if not self.encrypted_token:
            return ""
        cipher = self._get_cipher()
        decrypted_bytes = cipher.decrypt(self.encrypted_token.encode("utf-8"))
        return decrypted_bytes.decode("utf-8")

    def _get_cipher(self) -> Fernet:
        return Fernet(settings.ENCRYPTION_KEY.encode("utf-8"))
```

### 1.2 Модели счетов, снимков и позиций
📁 `backend/apps/portfolio/models.py`

```python
from django.db import models


class Account(models.Model):
    investor = models.ForeignKey(
        "users.InvestorUser",
        on_delete=models.CASCADE,
        related_name="accounts"
    )
    account_id = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
    )
    name = models.CharField(max_length=128)
    account_type = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=32, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class PortfolioSnapshot(models.Model):
    account = models.ForeignKey(
        Account, 
        on_delete=models.CASCADE,
        related_name="snapshots"
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    
    total_amount_portfolio = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    total_amount_shares = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    total_amount_bonds = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    total_amount_etf = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    total_amount_currencies = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    expected_yield = models.DecimalField(max_digits=18, decimal_places=4, default=0)


class Position(models.Model):
    snapshot = models.ForeignKey(
        PortfolioSnapshot,
        on_delete=models.CASCADE,
        related_name="positions"
    )
    figi = models.CharField(max_length=64, db_index=True)
    ticker = models.CharField(max_length=32, blank=True)
    name = models.CharField(max_length=256, blank=True)
    instrument_type = models.CharField(max_length=32)
    quantity = models.DecimalField(max_digits=18, decimal_places=4)
    current_price = models.DecimalField(max_digits=18, decimal_places=4)
    average_position_price = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    expected_yield = models.DecimalField(max_digits=18, decimal_places=4)
```

---

## Этап 2: Сервисный слой и транзакции

📁 `backend/apps/portfolio/services.py`

```python
from decimal import Decimal
from django.db import transaction
from t_tech.invest.utils import money_to_decimal, quotation_to_decimal

from .models import Account, PortfolioSnapshot, Position


def save_portfolio_snapshot(account: Account, portfolio_data) -> PortfolioSnapshot:
    """
    Атомарно сохраняет снимок портфеля и все позиции в БД.
    1. with transaction.atomic(): гарантирует откат изменений при ошибке.
    2. bulk_create: выполняет один общий SQL INSERT вместо 50 поштучных.
    """
    with transaction.atomic():
        portfoliosnapshot = PortfolioSnapshot.objects.create(
            account=account,
            total_amount_portfolio=money_to_decimal(portfolio_data.total_amount_portfolio),
            total_amount_shares=money_to_decimal(portfolio_data.total_amount_shares),
            total_amount_bonds=money_to_decimal(portfolio_data.total_amount_bonds),
            total_amount_etf=money_to_decimal(portfolio_data.total_amount_etf),
            total_amount_currencies=money_to_decimal(portfolio_data.total_amount_currencies),
            expected_yield=quotation_to_decimal(portfolio_data.expected_yield) if portfolio_data.expected_yield else Decimal("0"),
        )
        
        position_to_create = []
        for pos in portfolio_data.positions:
            position_to_create.append(
                Position(
                    snapshot=portfoliosnapshot,
                    figi=pos.figi,
                    instrument_type=pos.instrument_type,
                    quantity=quotation_to_decimal(pos.quantity),
                    current_price=money_to_decimal(pos.current_price),
                    average_position_price=money_to_decimal(pos.average_position_price),
                    expected_yield=quotation_to_decimal(pos.expected_yield) if pos.expected_yield else Decimal("0"),
                )
            )

        # Пакетная вставка: 1 SQL-запрос
        Position.objects.bulk_create(position_to_create)
        return portfoliosnapshot
```

---

## Этап 3: Инфраструктура брокера (Docker + Redis)

📁 `docker-compose.yml` (в корне проекта)

```yaml
services:
  redis:
    image: redis:alpine
    container_name: t_invest_redis
    restart: unless-stopped
    ports:
      - "6379:6379"
```

Команда запуска контейнера:
```bash
docker compose up -d redis
```

---

## Этап 4: Подключение Celery к Django

### 4.1 Настройки в `backend/config/settings.py`
```python
# Celery settings
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")
```

### 4.2 Точка входа в `backend/config/__init__.py`
```python
from .celery import app as celery_app

__all__ = ("celery_app",)
```

### 4.3 Инициализация и расписание в `backend/config/celery.py`
```python
import os 
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("t_invest")
app.config_from_object("django.conf:settings", namespace="CELERY")

# Автопоиск файлов tasks.py по всем apps
app.autodiscover_tasks()

# Расписание Celery Beat
app.conf.beat_schedule = {
    "sync-portfolios-every-hour": {
        "task": "portfolio.tasks.sync_portfolios",
        "schedule": 3600.0,  # Запуск каждый час
    },
}
```

---

## Этап 5: Фоновые задачи, ретраи и диспетчер

📁 `backend/apps/portfolio/tasks.py`

```python
import logging
from celery import shared_task
from t_tech.invest import Client
from t_tech.invest.exceptions import RequestError
from users.models import InvestorUser

from .models import Account
from .services import save_portfolio_snapshot

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    autoretry_for=(RequestError, ConnectionError),
    retry_backoff=True,         # Экспоненциальный откат: 2с -> 4с -> 8с -> 16с
    retry_backoff_max=300,      # Потолок задержки: 5 минут
    retry_jitter=True,          # Случайный разброс времени
    max_retries=5,              # Максимум 5 попыток
)
def sync_user_portfolio(self, user_id: int):
    """
    Рабочая таска: синхронизирует ОДНОГО пользователя.
    Изолирована: ошибка одного не ломает остальных.
    """
    user = InvestorUser.objects.filter(id=user_id).first()
    if not user:
        logger.warning(f"Пользователь #{user_id} не найден в базе данных.")
        return

    token = user.decrypted_token
    if not token:
        logger.warning(f"У пользователя #{user_id} отсутствует токен Т-Банка.")
        return

    try:
        with Client(token) as client:
            accounts_response = client.users.get_accounts()

            for acc in accounts_response.accounts:
                account, _ = Account.objects.update_or_create(
                    account_id=acc.id,
                    defaults={
                        "investor": user,
                        "name": acc.name,
                        "account_type": str(acc.type),
                        "status": str(acc.status),
                    },
                )

                portfolio = client.operations.get_portfolio(account_id=acc.id)
                snapshot = save_portfolio_snapshot(
                    account=account,
                    portfolio_data=portfolio,
                )
                logger.info(
                    f"✅ Снимок #{snapshot.id} сохранен для счета '{acc.name}' "
                    f"(инвестор #{user.id}, баланс: {snapshot.total_amount_portfolio} руб.)"
                )

    except RequestError as exc:
        # Если токен невалиден / отозван (401/UNAUTHENTICATED) — выходим без ретраев
        if "UNAUTHENTICATED" in str(exc) or "401" in str(exc):
            logger.error(f"❌ Токен пользователя #{user.id} недействителен: {exc}")
            return
        # Для остальных сетевых ошибок пробрасываем выше для autoretry
        raise


@shared_task
def sync_portfolios():
    """
    Диспетчер для Celery Beat (Fan-out).
    Находит всех активных инвесторов и ставит каждому отдельную задачу в Redis.
    """
    users = InvestorUser.objects.exclude(encrypted_token="")
    count = 0
    for user in users:
        sync_user_portfolio.delay(user.id)
        count += 1

    logger.info(f"📢 Диспетчер запланировал синхронизацию для {count} инвесторов.")
```

---

## Этап 6: REST API на Django REST Framework

### 6.1 Сериализаторы
📁 `backend/apps/portfolio/serializers.py`

```python
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
    # Вложенный сериализатор позиций:
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
```

### 6.2 Контроллер (ViewSet)
📁 `backend/apps/portfolio/views.py`

```python
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Account
from .serializers import AccountSerializer, PortfolioSnapshotSerializer


class AccountViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Account.objects.all()
    serializer_class = AccountSerializer

    # Кастомный эндпоинт: GET /api/v1/accounts/{id}/latest_snapshot/
    @action(detail=True, methods=["get"])
    def latest_snapshot(self, request, pk=None):
        account = self.get_object()
        # prefetch_related убирает проблему N+1 запросов при выборке позиций
        latest = account.snapshots.prefetch_related("positions").order_by("-created_at").first()

        if not latest:
            return Response({"detail": "Снимка нет"}, status=404)

        serializer = PortfolioSnapshotSerializer(latest)
        return Response(serializer.data)
```

### 6.3 Роутеры и URLs
📁 `backend/apps/portfolio/urls.py`
```python
from rest_framework.routers import DefaultRouter
from .views import AccountViewSet

router = DefaultRouter()
router.register("accounts", AccountViewSet, basename="account")

urlpatterns = router.urls
```

📁 `backend/config/urls.py`
```python
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("portfolio.urls")),
]
```

---

## 🚀 Шпаргалка консольных команд для запуска

```bash
# 1. Запустить Redis в Docker
docker compose up -d redis

# 2. Запустить воркер Celery
uv run --directory backend celery -A config worker --loglevel=info

# 3. Запустить планировщик Celery Beat (в отдельном окне)
uv run --directory backend celery -A config beat --loglevel=info

# 4. Запустить Django REST API сервер
uv run --directory backend python manage.py runserver

# 5. Ручной триггер синхронизации через shell (проверка очереди)
uv run --directory backend python manage.py shell -c "from portfolio.tasks import sync_portfolios; sync_portfolios.delay()"

# 6. Проверка эндпоинта через curl
curl -s http://127.0.0.1:8000/api/v1/accounts/1/latest_snapshot/
```
