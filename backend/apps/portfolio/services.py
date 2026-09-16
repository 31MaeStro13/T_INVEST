from decimal import Decimal
from django.db import transaction

from .models import Account, PortfolioSnapshot, Position


def decimal_confert(money) -> Decimal:
    if not money: 
        return Decimal("0")
    return Decimal(money.units) + Decimal(money.nano) / Decimal(10**9)
            

def save_portfolio_snaphot(account: Account, portfolio_data) -> PortfolioSnapshot:

    with transaction.atomic():
        portfoliosnapshot = PortfolioSnapshot.objects.create(
            account=account,
            total_amount_portfolio=decimal_confert(portfolio_data.total_amount_portfolio),
            total_amount_shares=decimal_confert(portfolio_data.total_amount_shares),
            total_amount_bonds=decimal_confert(portfolio_data.total_amount_bonds),
            total_amount_etf=decimal_confert(portfolio_data.total_amount_etf),
            total_amount_currencies=decimal_confert(portfolio_data.total_amount_currencies),
            expected_yield=decimal_confert(portfolio_data.expected_yield),

        )
        position_to_create = []

        for pos in portfolio_data.positions:
            position_to_create.append(
                Position(
                snapshot=portfoliosnapshot,
                figi=pos.figi,
                #ticker=pos.ticker,
                #name=pos.name,
                instrument_type=pos.instrument_type,
                quantity=decimal_confert(pos.quantity),
                current_price=decimal_confert(pos.current_price),
                average_position_price=decimal_confert(pos.average_position_price),
                expected_yield=decimal_confert(pos.expected_yield),
            )
        )

        Position.objects.bulk_create(position_to_create) # bulk_create используется для того чтобы не создавать 50 insert а сделать один большой insert
        return portfoliosnapshot
