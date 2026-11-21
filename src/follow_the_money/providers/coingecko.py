"""CoinGecko provider (historical prices, free demo API key required).

API reference: https://docs.coingecko.com/v3.0.1/reference/coins-id-history
``/coins/{id}/history`` returns a snapshot at 00:00:00 UTC of the given date,
passed to the Demo API as ``dd-mm-yyyy``.
Prices are returned in USD and parsed as ``Decimal``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import httpx

from ..errors import ProviderError
from ._http import HttpClient

NAME = "coingecko"
BASE_URL = "https://api.coingecko.com/api/v3"
KEY_VARIABLE = "COINGECKO_API_KEY"
KEY_HEADER = "x-cg-demo-api-key"

COIN_IDS = {
    "bitcoin": "bitcoin",
    "btc": "bitcoin",
    "ethereum": "ethereum",
    "eth": "ethereum",
}


def _bad(reason: str) -> ProviderError:
    return ProviderError(NAME, f"unexpected response: {reason}")


def coin_id(coin: str) -> str:
    """Map a coin name or ticker to the CoinGecko coin id."""
    try:
        return COIN_IDS[coin.strip().lower()]
    except KeyError:
        raise ValueError(f"Unsupported coin: {coin!r}") from None


def parse_price(raw: Any) -> Decimal:
    """Extract the USD price from a ``/coins/{id}/history`` response."""
    try:
        value = raw["market_data"]["current_price"]["usd"]
    except (KeyError, TypeError):
        raise _bad("no USD price for the requested date") from None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise _bad("price is not a number")
    try:
        price = Decimal(str(value))
    except ArithmeticError:
        raise _bad("price is not a number") from None
    if not price.is_finite() or price < 0:
        raise _bad("price is not a valid number")
    return price


class CoinGeckoProvider:
    """Historical USD prices backed by the CoinGecko API."""

    name = NAME
    chain = "price"
    requires_key = KEY_VARIABLE

    def __init__(
        self,
        api_key: str,
        base_url: str = BASE_URL,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key:
            raise ValueError(f"{KEY_VARIABLE} must not be empty")
        self._http = HttpClient(
            NAME,
            base_url,
            secrets=(api_key,),
            headers={KEY_HEADER: api_key},
            client=client,
        )

    def get_price(self, coin: str, on: date) -> Decimal:
        """Return the USD price of ``coin`` on the UTC date ``on``."""
        raw = self._http.get_json(
            f"/coins/{coin_id(coin)}/history",
            {"date": on.strftime("%d-%m-%Y"), "localization": "false"},
        )
        return parse_price(raw)
