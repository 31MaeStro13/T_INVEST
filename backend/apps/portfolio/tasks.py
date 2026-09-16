import logging
import os 

from t_tech.invest import Client
from celery import shared_task
from .models import Account
from users.models import InvestorUser
from .services import save_portfolio_snaphot

logger = logging.getLogger(__name__)

token = os.getenv("T_BANK_READ_ONLY_INVEST_TOKEN")

@shared_task
def sync_portfolios():
    with Client(token) as client:
        accounts_response = client.users.get_accounts() # получил json где у меня инфа по аккаунту токен которого я закинул

        user = InvestorUser.objects.get() # подтянул первый элемент модели, нужно подтягивать по токену id пользователя

        for acc in accounts_response.accounts:
            account, _ = Account.objects.update_or_create( # два элемента возвращает
                account_id=acc.id,
                defaults={
                    "investor": user,
                    "name": acc.name,
                    "account_type": str(acc.type),
                    "status": str(acc.status),
                }
            )

            portfolio = client.operations.get_portfolio(account_id=acc.id)

            snapshot = save_portfolio_snaphot(
                account=account,
                portfolio_data=portfolio
            )

