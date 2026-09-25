import logging
import os

from celery import shared_task
from t_tech.invest import Client
from t_tech.invest.exceptions import RequestError
from users.models import InvestorUser
from django.core.cache import cache

from .models import Account
from .services import save_portfolio_snapshot

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    autoretry_for=(RequestError, ConnectionError),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=5,
)
def sync_user_portfolio(self, user_id: int):
    """
    Синхронизирует счета и портфель ОДНОГО конкретного пользователя.
    Изолирована: сбой у этого инвестора не сломает синхронизацию остальных.
    """
    user = InvestorUser.objects.filter(id=user_id).first()
    if not user:
        logger.warning(f"Пользователь #{user_id} не найден в базе данных.")
        return

    # Получаем активные токены пользователя
    tokens_to_sync = list(user.broker_tokens.filter(is_active=True))
    if not tokens_to_sync and user.encrypted_token:
        # Fallback для совместимости
        tokens_to_sync = [user]

    if not tokens_to_sync:
        logger.warning(f"У пользователя #{user_id} отсутствует активный токен Т-Банка.")
        return

    for token_obj in tokens_to_sync:
        token = token_obj.decrypted_token
        if not token:
            continue

        broker_token = token_obj if hasattr(token_obj, "user_id") else None

        try:
            with Client(token) as client:
                accounts_response = client.users.get_accounts()

                for acc in accounts_response.accounts:
                    account, _ = Account.objects.update_or_create(
                        account_id=acc.id,
                        defaults={
                            "investor": user,
                            "broker_token": broker_token,
                            "name": acc.name,
                            "account_type": str(acc.type),
                            "status": str(acc.status),
                        },
                    )

                    # Если у пользователя еще не выбран активный счет — ставим этот
                    if not user.active_account:
                        user.active_account = account
                        user.save(update_fields=["active_account"])

                    portfolio = client.operations.get_portfolio(account_id=acc.id)
                    snapshot = save_portfolio_snapshot(
                        account=account,
                        portfolio_data=portfolio,
                        client=client,
                    )
                    logger.info(
                        f"✅ Снимок #{snapshot.id} сохранен для счета '{acc.name}' "
                        f"(инвестор #{user.id}, баланс: {snapshot.total_amount_portfolio} руб.)"
                    )
                    
                    cache.delete(f"chart:account:{account.id}")
                    cache.delete(f"chart:consolidated:{user.id}")

        except RequestError as exc:
            if "UNAUTHENTICATED" in str(exc) or "401" in str(exc):
                logger.error(f"❌ Токен {token_obj} пользователя #{user.id} недействителен: {exc}")
                continue
            raise


@shared_task
def sync_portfolios():
    """
    Диспетчер для Celery Beat.
    Раз в час находит всех пользователей с токенами и ставит каждому отдельную задачу.
    """
    user_ids = InvestorUser.objects.exclude(encrypted_token="").values_list('id', flat=True).iterator(chunk_size=2000)
    count = 0
    for user in user_ids:
        sync_user_portfolio.delay(user.id)
        count += 1

    logger.info(f"📢 Диспетчер запланировал синхронизацию для {count} инвесторов.")
# не я написал
