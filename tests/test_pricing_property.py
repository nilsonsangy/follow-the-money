"""Property-based tests for USD conversion by date.

Feature: crypto-tracing, Property 10: conversion to USD by date.

**Validates: Requirements 9.9**
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from hypothesis import given, strategies as st

from follow_the_money.pricing import price_table_lookup, to_usd

amounts = st.decimals(
    min_value=Decimal("0"), max_value=Decimal("1000000"), places=8, allow_nan=False
)
prices = st.decimals(
    min_value=Decimal("0.01"), max_value=Decimal("1000000"), places=2, allow_nan=False
)
dates = st.dates(min_value=date(2010, 1, 1), max_value=date(2100, 1, 1))
coins = st.sampled_from(["BTC", "ETH", "LTC"])


@given(
    amount=amounts,
    coin=coins,
    on=dates,
    price=prices,
    hour=st.integers(0, 23),
    other_offset=st.integers(min_value=1, max_value=3000),
    other_price=prices,
)
def test_usd_is_amount_times_price_of_the_calendar_date(
    amount, coin, on, price, hour, other_offset, other_price
):
    other = on + timedelta(days=other_offset)
    lookup = price_table_lookup({(coin, on): price, (coin, other): other_price})
    moment = datetime(on.year, on.month, on.day, hour, tzinfo=timezone.utc)
    assert to_usd(amount, coin, on, lookup) == amount * price
    assert to_usd(amount, coin, moment, lookup) == amount * price
