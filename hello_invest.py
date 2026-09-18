import asyncio
import logging
import os
import sys
import django


from t_tech.invest import AsyncClient
from decimal import Decimal


sys.path.insert(0, os.path.abspath("backend"))
sys.path.insert(0, os.path.abspath("backend/apps"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

django.setup()

from asgiref.sync import sync_to_async
from users.models import InvestorUser
from portfolio.models import Account
from portfolio.services import save_portfolio_snapshot


logger = logging.getLogger(__name__)

token = os.getenv("T_BANK_READ_ONLY_INVEST_TOKEN")

        
def decimal_confert(money) -> Decimal:
    return Decimal(money.units) + Decimal(money.nano) / Decimal(10**9)
            
 
    

async def main():
    async with AsyncClient(token) as client:
        accounts_response = await client.users.get_accounts()
        user = await sync_to_async(InvestorUser.objects.get)()


        for acc in accounts_response.accounts:
            account, _ = await sync_to_async(Account.objects.update_or_create)( # два элемента возвращает
                account_id=acc.id,
                defaults={
                    "investor": user,
                    "name": acc.name,
                    "account_type": str(acc.type),
                    "status": str(acc.status),
                }
            )
            portfolio = await client.operations.get_portfolio(account_id=acc.id)
            snapshot = await sync_to_async(save_portfolio_snaphot)(
                account=account,
                portfolio_data=portfolio
            )
            print(f"✅ Сохранен снимок #{snapshot.id}")
            balance = decimal_confert(portfolio.total_amount_portfolio)
            currency = portfolio.total_amount_portfolio.currency.upper()
            print(f"💼 Счет: «{acc.name}» (ID: {acc.id})")
            print(f"💰 Баланс: {balance:.2f} {currency}")

if __name__ == '__main__':
    asyncio.run(main())



