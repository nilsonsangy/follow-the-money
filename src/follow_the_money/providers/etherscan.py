"""Etherscan provider (Ethereum, free API key required).

API reference: https://docs.etherscan.io (API V2, single ``/v2/api`` endpoint
selected by the ``chainid`` parameter; ``1`` is Ethereum mainnet).
Amounts are returned in wei (or token base units) and converted to ``Decimal``.

``kind`` values: ``native`` (ETH transfer), ``contract_call`` (call to, or
creation of, a contract), ``token`` (ERC-20 transfer) and ``internal``
(internal transaction).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx

from ..errors import ProviderError, RateLimitError
from ..models import Balance, Transaction, TxInput, TxOutput
from ._http import HttpClient

NAME = "etherscan"
BASE_URL = "https://api.etherscan.io/v2"
CHAIN_ID = "1"
KEY_VARIABLE = "ETHERSCAN_API_KEY"
WEI_PER_ETH = Decimal(10) ** 18
MAX_PAGE_SIZE = 1000  # upper bound for one request, independent of ``limit``


def _bad(reason: str) -> ProviderError:
    return ProviderError(NAME, f"unexpected response: {reason}")


def unwrap_result(raw: Any) -> Any:
    """Return ``result`` from an Etherscan envelope, or raise a provider error.

    ``status == "0"`` with an empty list means "no transactions" and yields
    ``[]``. Rate-limit messages raise :class:`RateLimitError`; any other
    ``status == "0"`` raises :class:`ProviderError` with the API's message.
    """
    if not isinstance(raw, dict) or "result" not in raw:
        raise _bad("missing 'result'")
    result = raw["result"]
    if str(raw.get("status")) == "1":
        return result
    if isinstance(result, list):
        return result
    text = f"{raw.get('message', '')} {result}".lower()
    if "rate limit" in text:
        raise RateLimitError(NAME)
    raise ProviderError(NAME, f"API error: {raw.get('message')}: {result}")


def _timestamp(value: Any) -> datetime:
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        raise _bad("invalid timestamp") from None


def _units(value: Any, decimals: int) -> Decimal:
    try:
        return Decimal(str(value)) / (Decimal(10) ** decimals)
    except (ArithmeticError, ValueError):
        raise _bad("amount is not a number") from None


def _address(value: Any) -> str | None:
    return value.lower() if isinstance(value, str) and value else None


def _build(raw: Any, value: Decimal, kind: str) -> Transaction:
    if not isinstance(raw, dict):
        raise _bad("transaction is not an object")
    txid = raw.get("hash")
    if not isinstance(txid, str):
        raise _bad("missing transaction hash")
    sender = _address(raw.get("from"))
    receiver = _address(raw.get("to"))
    return Transaction(
        chain="ethereum",
        txid=txid,
        timestamp=_timestamp(raw.get("timeStamp")),
        inputs=(TxInput(sender, value, None),),
        outputs=(TxOutput(receiver, value),),
        source=NAME,
        kind=kind,
    )


def parse_native_transaction(raw: dict[str, Any]) -> Transaction:
    """Normalize one item of ``action=txlist``.

    A transaction that creates a contract (empty ``to``), or sends input data
    to an address, has ``kind="contract_call"``; a plain transfer is ``native``.
    """
    if not isinstance(raw, dict):
        raise _bad("transaction is not an object")
    input_data = raw.get("input")
    has_input = isinstance(input_data, str) and input_data not in ("", "0x")
    creates = not raw.get("to")
    kind = "contract_call" if creates or has_input else "native"
    return _build(raw, _units(raw.get("value", "0"), 18), kind)


def parse_token_transfer(raw: dict[str, Any]) -> Transaction:
    """Normalize one item of ``action=tokentx`` (kind ``token``)."""
    if not isinstance(raw, dict):
        raise _bad("token transfer is not an object")
    try:
        decimals = int(raw.get("tokenDecimal") or 0)
    except (TypeError, ValueError):
        raise _bad("invalid token decimals") from None
    return _build(raw, _units(raw.get("value", "0"), decimals), "token")


def parse_internal_transaction(raw: dict[str, Any]) -> Transaction:
    """Normalize one item of ``action=txlistinternal`` (kind ``internal``)."""
    return _build(raw, _units(raw.get("value", "0") if isinstance(raw, dict) else "0", 18), "internal")


def parse_list(raw: Any, parser: Any) -> list[Transaction]:
    """Unwrap an Etherscan envelope and apply ``parser`` to every result item."""
    result = unwrap_result(raw)
    if not isinstance(result, list):
        raise _bad("expected a list result")
    return [parser(item) for item in result]


def parse_balance(address: str, raw: Any) -> Balance:
    """Normalize ``action=balance`` into a balance in ETH."""
    result = unwrap_result(raw)
    if isinstance(result, (list, dict)):
        raise _bad("malformed balance")
    return Balance(address, "ethereum", _units(result, 18), NAME)


class EtherscanProvider:
    """Ethereum provider backed by the Etherscan API V2 (requires a free key)."""

    name = NAME
    chain = "ethereum"
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

    def _query(self, action: str, address: str, **extra: Any) -> Any:
        params = {
            "chainid": CHAIN_ID,
            "module": "account",
            "action": action,
            "address": address,
            "apikey": self._key,
            **extra,
        }
        return self._http.get_json("/api", params)

    def get_balance(self, address: str) -> Balance:
        return parse_balance(address, self._query("balance", address, tag="latest"))

    def _list(self, action: str, parser: Any, address: str, limit: int) -> list[Transaction]:
        size = max(1, min(limit, MAX_PAGE_SIZE))
        raw = self._query(action, address, page=1, offset=size, sort="desc")
        return parse_list(raw, parser)

    def get_transactions(self, address: str, limit: int) -> list[Transaction]:
        """Return up to ``limit`` transactions of every kind, newest first."""
        merged = (
            self._list("txlist", parse_native_transaction, address, limit)
            + self._list("tokentx", parse_token_transfer, address, limit)
            + self._list("txlistinternal", parse_internal_transaction, address, limit)
        )
        merged.sort(key=lambda tx: tx.timestamp, reverse=True)
        return merged[:limit]
