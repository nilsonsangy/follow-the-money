"""Blockscout provider (Ethereum, open, no API key).

API reference: https://docs.blockscout.com/devs/apis
Uses the public REST v2 endpoints of the Ethereum mainnet instance:
``/addresses/{hash}``, ``/transactions``, ``/token-transfers`` and
``/internal-transactions``. Amounts are converted from the smallest unit
(wei, or token base units) to ``Decimal``.

``kind`` values: ``native`` (ETH transfer), ``contract_call`` (call to, or
creation of, a contract), ``token`` (token transfer) and ``internal``
(internal transaction).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx

from ..errors import ProviderError
from ..models import Balance, Transaction, TxInput, TxOutput
from ._http import HttpClient

NAME = "blockscout"
BASE_URL = "https://eth.blockscout.com/api/v2"
WEI_PER_ETH = Decimal(10) ** 18
MAX_PAGES = 20  # hard bound on pagination, independent of ``limit``


def _bad(reason: str) -> ProviderError:
    return ProviderError(NAME, f"unexpected response: {reason}")


def _address(party: Any) -> str | None:
    if party is None:
        return None
    if isinstance(party, dict):
        value = party.get("hash")
        return value if isinstance(value, str) else None
    raise _bad("malformed address object")


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise _bad("missing timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise _bad("invalid timestamp") from None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _units(value: Any, decimals: int) -> Decimal:
    try:
        return Decimal(str(value)) / (Decimal(10) ** decimals)
    except (ArithmeticError, ValueError):
        raise _bad("amount is not a number") from None


def _txid(raw: dict[str, Any], *names: str) -> str:
    for name in names:
        value = raw.get(name)
        if isinstance(value, str):
            return value
    raise _bad("missing transaction hash")


def _build(
    raw: dict[str, Any], txid: str, value: Decimal, kind: str
) -> Transaction:
    sender = _address(raw.get("from"))
    receiver = _address(raw.get("to"))
    return Transaction(
        chain="ethereum",
        txid=txid,
        timestamp=_timestamp(raw.get("timestamp")),
        inputs=(TxInput(sender, value, None),),
        outputs=(TxOutput(receiver, value),),
        source=NAME,
        kind=kind,
    )


def parse_native_transaction(raw: dict[str, Any]) -> Transaction:
    """Normalize one item of ``/addresses/{hash}/transactions``.

    A transaction that creates a contract, or calls one with input data, has
    ``kind="contract_call"``; a plain ETH transfer has ``kind="native"``.
    """
    if not isinstance(raw, dict):
        raise _bad("transaction is not an object")
    to = raw.get("to")
    input_data = raw.get("raw_input")
    if isinstance(input_data, str):
        has_input = input_data not in ("", "0x")
    else:
        has_input = bool(raw.get("method"))
    is_contract = to is None or (isinstance(to, dict) and bool(to.get("is_contract")))
    kind = "contract_call" if is_contract and (to is None or has_input) else "native"
    return _build(raw, _txid(raw, "hash"), _units(raw.get("value", "0"), 18), kind)


def parse_token_transfer(raw: dict[str, Any]) -> Transaction:
    """Normalize one item of ``/addresses/{hash}/token-transfers`` (kind ``token``).

    Amounts use the token's own decimals. NFT transfers without a numeric
    ``total.value`` are counted as a single unit.
    """
    if not isinstance(raw, dict):
        raise _bad("token transfer is not an object")
    total = raw.get("total") or {}
    token = raw.get("token") or {}
    decimals_raw = total.get("decimals") or token.get("decimals") or 0
    try:
        decimals = int(decimals_raw)
    except (TypeError, ValueError):
        raise _bad("invalid token decimals") from None
    value = _units(total["value"], decimals) if total.get("value") is not None else Decimal(1)
    txid = _txid(raw, "transaction_hash", "tx_hash", "hash")
    return _build(raw, txid, value, "token")


def parse_internal_transaction(raw: dict[str, Any]) -> Transaction:
    """Normalize one item of ``/addresses/{hash}/internal-transactions`` (kind ``internal``)."""
    if not isinstance(raw, dict):
        raise _bad("internal transaction is not an object")
    txid = _txid(raw, "transaction_hash", "tx_hash", "hash")
    return _build(raw, txid, _units(raw.get("value", "0"), 18), "internal")


def parse_items(raw: Any, parser: Any) -> list[Transaction]:
    """Apply ``parser`` to every element of a paged response's ``items``."""
    if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
        raise _bad("expected an object with an 'items' list")
    return [parser(item) for item in raw["items"]]


def parse_balance(address: str, raw: Any) -> Balance:
    """Normalize ``/addresses/{hash}`` into a balance in ETH."""
    if not isinstance(raw, dict) or raw.get("coin_balance") is None:
        raise _bad("missing coin_balance")
    return Balance(address, "ethereum", _units(raw["coin_balance"], 18), NAME)


class BlockscoutProvider:
    """Open Ethereum provider backed by the Blockscout REST v2 API."""

    name = NAME
    chain = "ethereum"
    requires_key = None

    def __init__(
        self, base_url: str = BASE_URL, client: httpx.Client | None = None
    ) -> None:
        self._http = HttpClient(NAME, base_url, client=client)

    def get_balance(self, address: str) -> Balance:
        return parse_balance(address, self._http.get_json(f"/addresses/{address}"))

    def _collect(self, path: str, parser: Any, limit: int) -> list[Transaction]:
        result: list[Transaction] = []
        params: dict[str, Any] | None = None
        for _ in range(MAX_PAGES):
            raw = self._http.get_json(path, params)
            result.extend(parse_items(raw, parser))
            params = raw.get("next_page_params")
            if len(result) >= limit or not params:
                break
        return result[:limit]

    def get_transactions(self, address: str, limit: int) -> list[Transaction]:
        """Return up to ``limit`` transactions of every kind, newest first."""
        base = f"/addresses/{address}"
        merged = (
            self._collect(f"{base}/transactions", parse_native_transaction, limit)
            + self._collect(f"{base}/token-transfers", parse_token_transfer, limit)
            + self._collect(f"{base}/internal-transactions", parse_internal_transaction, limit)
        )
        merged.sort(key=lambda tx: tx.timestamp, reverse=True)
        return merged[:limit]
