import asyncio
import logging
import os
import sys

from config.config import Config, load_config
from t_tech.invest import AsyncClient
from decimal import Decimal

config: Config = load_config()


logger = logging.getLogger(__name__)


        
def decimal_confert(money) -> Decimal:
    return Decimal(money.units) + Decimal(money.nano) / Decimal(10**9)
            

    

async def main():
    async with AsyncClient(config.tbank.token) as client:
        accounts_response = await client.users.get_accounts()
        
        for acc in accounts_response.accounts:

            portfolio = await client.operations.get_portfolio(account_id=acc.id)
            balance = decimal_confert(portfolio.total_amount_portfolio)
            currency = portfolio.total_amount_portfolio.currency.upper()
            print(f"💼 Счет: «{acc.name}» (ID: {acc.id})")
            print(f"💰 Баланс: {balance:.2f} {currency}")

if __name__ == '__main__':
    asyncio.run(main())



