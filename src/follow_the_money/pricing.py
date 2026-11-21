"""Conversion of coin amounts to US dollars using the price on the transaction date.

The module is pure: the price lookup is an injected callable with the same
signature as ``CoinGeckoProvider.get_price(coin, on)``, so no network access
happens here.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal

from .models import Transaction

PriceFn = Callable[[str, date], Decimal]


def _as_date(on: date | datetime) -> date:
    return on.date() if isinstance(on, datetime) else on


def to_usd(amount: Decimal, coin: str, on: date | datetime, get_price: PriceFn) -> Decimal:
    """Return ``amount`` of ``coin`` in USD at the price of the given date.

    Only the price of ``on`` is requested; prices of other dates never
    influence the result.
    """
    return amount * get_price(coin, _as_date(on))


def transaction_usd(tx: Transaction, coin: str, get_price: PriceFn) -> Decimal:
    """Return the total output value of ``tx`` in USD at the transaction date."""
    total = sum((out.value for out in tx.outputs), Decimal(0))
    return to_usd(total, coin, tx.timestamp, get_price)


def price_table_lookup(prices: dict[tuple[str, date], Decimal]) -> PriceFn:
    """Build a ``get_price`` function backed by a fixed ``(coin, date)`` table."""

    def get_price(coin: str, on: date) -> Decimal:
        try:
            return prices[(coin, on)]
        except KeyError:
            raise KeyError(f"No price for {coin} on {on.isoformat()}") from None

    return get_price
