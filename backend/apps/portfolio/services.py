from decimal import Decimal
from django.db import transaction

from .models import Account, PortfolioSnapshot, Position
from t_tech.invest.utils import money_to_decimal, quotation_to_decimal



def save_portfolio_snapshot(account: Account, portfolio_data) -> PortfolioSnapshot:

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
                #ticker=pos.ticker,
                #name=pos.name,
                instrument_type=pos.instrument_type,
                quantity=quotation_to_decimal(pos.quantity),
                current_price=money_to_decimal(pos.current_price),
                average_position_price=money_to_decimal(pos.average_position_price),
                expected_yield=quotation_to_decimal(pos.expected_yield) if pos.expected_yield else Decimal("0"),
            )
        )

        Position.objects.bulk_create(position_to_create) # bulk_create используется для того чтобы не создавать 50 insert а сделать один большой insert
        return portfoliosnapshot
