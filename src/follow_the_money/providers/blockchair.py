"""Blockchair provider (Bitcoin, free API key optional for higher volume).

API reference: https://blockchair.com/api/docs
Uses ``/bitcoin/dashboards/address/{address}`` for the balance and the list of
transaction hashes, and ``/bitcoin/dashboards/transactions/{hashes}`` for
inputs and outputs. Amounts are returned in satoshis and converted to BTC as
``Decimal``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx

from ..errors import ProviderError
from ..models import Balance, Transaction, TxInput, TxOutput
from ._http import HttpClient

NAME = "blockchair"
BASE_URL = "https://api.blockchair.com"
KEY_VARIABLE = "BLOCKCHAIR_API_KEY"
SATOSHIS_PER_BTC = Decimal(100_000_000)
BATCH_SIZE = 10  # hashes per batch request, fixed by the API
MAX_ADDRESS_TXS = 10_000  # upper bound of the ``limit`` parameter


def _bad(reason: str) -> ProviderError:
    return ProviderError(NAME, f"unexpected response: {reason}")


def _data(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or not isinstance(raw.get("data"), dict):
        raise _bad("missing 'data'")
    return raw["data"]


def _btc(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise _bad("amount is not an integer number of satoshis")
    try:
        return Decimal(int(value)) / SATOSHIS_PER_BTC
    except ValueError:
        raise _bad("amount is not an integer number of satoshis") from None


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise _bad("missing transaction time")
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        raise _bad("invalid transaction time") from None


def _recipient(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def parse_transaction(entry: dict[str, Any]) -> Transaction:
    """Normalize one ``{transaction, inputs, outputs}`` entry of the dashboard."""
    try:
        header = entry["transaction"]
        txid = header["hash"]
        if not isinstance(txid, str):
            raise _bad("malformed transaction")
        timestamp = _time(header.get("time"))
        inputs = tuple(
            TxInput(
                _recipient(item.get("recipient")),
                _btc(item["value"]),
                item.get("transaction_hash"),
            )
            for item in entry["inputs"]
        )
        outputs = tuple(
            TxOutput(_recipient(item.get("recipient")), _btc(item["value"]))
            for item in entry["outputs"]
        )
    except ProviderError:
        raise
    except (KeyError, TypeError, AttributeError):
        raise _bad("malformed transaction") from None
    return Transaction(
        chain="bitcoin",
        txid=txid,
        timestamp=timestamp,
        inputs=inputs,
        outputs=outputs,
        source=NAME,
        kind="native",
    )


def parse_transactions(raw: Any) -> list[Transaction]:
    """Normalize a ``dashboards/transactions`` response (one entry per hash)."""
    return [parse_transaction(entry) for entry in _data(raw).values()]


def parse_address_dashboard(address: str, raw: Any) -> tuple[Balance, list[str]]:
    """Return the balance and transaction hashes of an address dashboard."""
    entry = _data(raw).get(address)
    if not isinstance(entry, dict):
        raise _bad("address not present in response")
    try:
        balance = _btc(entry["address"]["balance"])
    except (KeyError, TypeError):
        raise _bad("malformed address dashboard") from None
    hashes = entry.get("transactions") or []
    if not isinstance(hashes, list) or not all(isinstance(h, str) for h in hashes):
        raise _bad("malformed transaction list")
    return Balance(address, "bitcoin", balance, NAME), hashes


class BlockchairProvider:
    """Bitcoin provider backed by the Blockchair REST API."""

    name = NAME
    chain = "bitcoin"
    requires_key = KEY_VARIABLE

    def __init__(
        self,
        api_key: str,
        base_url: str = BASE_URL,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key:
            raise ValueError(f"{KEY_VARIABLE} must not be empty")
        self._key = api_key
        self._http = HttpClient(NAME, base_url, secrets=(api_key,), client=client)

    def _dashboard(self, address: str, limit: int) -> tuple[Balance, list[str]]:
        params = {"limit": max(1, min(limit, MAX_ADDRESS_TXS)), "key": self._key}
        raw = self._http.get_json(f"/bitcoin/dashboards/address/{address}", params)
        return parse_address_dashboard(address, raw)

    def get_balance(self, address: str) -> Balance:
        return self._dashboard(address, 1)[0]

    def get_transactions(self, address: str, limit: int) -> list[Transaction]:
        """Return up to ``limit`` transactions, newest first."""
        _, hashes = self._dashboard(address, limit)
        result: list[Transaction] = []
        for start in range(0, min(len(hashes), limit), BATCH_SIZE):
            batch = hashes[start : min(start + BATCH_SIZE, limit)]
            raw = self._http.get_json(
                f"/bitcoin/dashboards/transactions/{','.join(batch)}", {"key": self._key}
            )
            result.extend(parse_transactions(raw))
        result.sort(key=lambda tx: tx.timestamp, reverse=True)
        return result[:limit]
