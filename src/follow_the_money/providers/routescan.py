"""Routescan provider (Ethereum, open, no API key).

Routescan exposes an Etherscan-compatible API for each network. The Ethereum
mainnet endpoint answers without a key under a free per-second and per-day
limit that the Routescan documentation states. This provider reuses the
Etherscan request and parsing code, with that endpoint and no key, and
labels every result with its own source name.
"""
from __future__ import annotations

from dataclasses import replace
import httpx

from ..models import Balance, Transaction, TransactionDetail
from .etherscan import EtherscanProvider

NAME = "routescan"
BASE_URL = "https://api.routescan.io/v2/network/mainnet/evm/1/etherscan"


class RoutescanProvider(EtherscanProvider):
    """Open Ethereum provider backed by the Routescan Etherscan-compatible API."""

    name = NAME
    chain = "ethereum"
    requires_key = None

    def __init__(
        self,
        base_url: str = BASE_URL,
        client: httpx.Client | None = None,
        min_interval: float | None = None,
    ) -> None:
        super().__init__(None, base_url=base_url, client=client, min_interval=min_interval)

    def get_balance(self, address: str) -> Balance:
        return replace(super().get_balance(address), source=NAME)

    def get_transactions(self, address: str, limit: int) -> list[Transaction]:
        return [replace(tx, source=NAME) for tx in super().get_transactions(address, limit)]

    def get_transaction(self, txid: str) -> TransactionDetail:
        detail = super().get_transaction(txid)
        return replace(
            detail,
            source=NAME,
            internal=tuple(replace(tx, source=NAME) for tx in detail.internal),
        )