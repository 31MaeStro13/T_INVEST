import logging
import os

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
        # Если токен отозван или невалиден (401/UNAUTHENTICATED) — не ретраим впустую 5 раз
        if "UNAUTHENTICATED" in str(exc) or "401" in str(exc):
            logger.error(f"❌ Токен пользователя #{user.id} недействителен: {exc}")
            return
        # Для всех остальных сетевых ошибок пробрасываем выше, чтобы сработал autoretry
        raise


@shared_task
def sync_portfolios():
    """
    Диспетчер для Celery Beat.
    Раз в час находит всех пользователей с токенами и ставит каждому отдельную задачу.
    """
    users = InvestorUser.objects.exclude(encrypted_token="")
    count = 0
    for user in users:
        sync_user_portfolio.delay(user.id)
        count += 1

    logger.info(f"📢 Диспетчер запланировал синхронизацию для {count} инвесторов.")
# не я написал
