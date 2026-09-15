from django.db import models

# Create your models here.

class Account(models.Model):

    investor = models.ForeignKey(
        "users.InvestorUser",
        on_delete = models.CASCADE,
        related_name = "accounts"
    )

    account_id = models.CharField(
        max_length = 64,
        unique = True,
        db_index = True,
    )

    name = models.CharField(max_length=128)

    account_type = models.CharField(
        max_length=64, 
        blank=True
    )

    status = models.CharField(
        max_length=32,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)


class PortfolioSnapshot(models.Model):

    account = models.ForeignKey(
        Account, 
        on_delete=models.CASCADE,
        related_name="snapshots"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True 
    )

    total_amount_portfolio = models.DecimalField(
        max_digits=18,
        decimal_places=4, 
        default=0
    )

    total_amount_shares = models.DecimalField(
        max_digits=18,
        decimal_places=4, 
        default=0
    )  
     
    total_amount_bonds = models.DecimalField(
        max_digits=18,
        decimal_places=4, 
        default=0
    )

    total_amount_etf = models.DecimalField(
        max_digits=18,
        decimal_places=4, 
        default=0
    )

    total_amount_currencies = models.DecimalField(
        max_digits=18,
        decimal_places=4, 
        default=0
    )

    expected_yield = models.DecimalField(
        max_digits=18,
        decimal_places=4, 
        default=0
    )

class Position(models.Model):

    snapshot = models.ForeignKey(
        PortfolioSnapshot,
        on_delete=models.CASCADE,
        related_name="positions"
    )

    figi = models.CharField(
        max_length=64,
        db_index=True
    )

    ticker = models.CharField(
        max_length=32,
        blank=True
    )

    name = models.CharField(
        max_length=256,
        blank=True
    )

    instrument_type = models.CharField(
        max_length=32
    )

    quantity = models.DecimalField(
        max_digits=18, 
        decimal_places=4
    )

    current_price = models.DecimalField(
        max_digits=18, 
        decimal_places=4
    )

    average_position_price = models.DecimalField(
        max_digits=18, 
        decimal_places=4,
        null=True, 
        blank=True
    )

    expected_yield = models.DecimalField(
        max_digits=18, 
        decimal_places=4
    )
