"""Etherscan provider (Ethereum, free API key required).

API reference: https://docs.etherscan.io (API V2, single ``/v2/api`` endpoint
selected by the ``chainid`` parameter; ``1`` is Ethereum mainnet).
Amounts are returned in wei (or token base units) and converted to ``Decimal``.

``kind`` values: ``native`` (ETH transfer), ``contract_call`` (call to, or
creation of, a contract), ``token`` (ERC-20 transfer) and ``internal``
(internal transaction).
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx

from ..errors import ProviderError, RateLimitError
from ..models import Balance, Transaction, TransactionDetail, TxInput, TxOutput
from ._http import HttpClient

NAME = "etherscan"
BASE_URL = "https://api.etherscan.io/v2"
CHAIN_ID = "1"
KEY_VARIABLE = "ETHERSCAN_API_KEY"
WEI_PER_ETH = Decimal(10) ** 18
MAX_PAGE_SIZE = 1000  # upper bound for one request, independent of ``limit``
# The free plan allows 3 calls per second, counted on the server side. Half a
# second between requests keeps a margin for network jitter without retrying.
MIN_INTERVAL = 0.5


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


def _hex_int(value: Any, field: str) -> int:
    if not isinstance(value, str) or not value.startswith("0x"):
        raise _bad(f"invalid {field}")
    try:
        return int(value, 16)
    except ValueError:
        raise _bad(f"invalid {field}") from None


def unwrap_proxy(raw: Any) -> Any:
    """Return ``result`` from a JSON-RPC style ``module=proxy`` response.

    Proxy calls answer ``{"jsonrpc", "id", "result"}``. Errors and rate limits
    come back in the ``status``/``message`` envelope instead, which
    :func:`unwrap_result` already handles.
    """
    if isinstance(raw, dict) and "status" in raw:
        return unwrap_result(raw)
    if not isinstance(raw, dict) or "result" not in raw:
        raise _bad("missing 'result'")
    return raw["result"]


def parse_transaction_detail(tx: Any, receipt: Any, block: Any, internal: Any) -> TransactionDetail:
    """Normalize the proxy transaction, receipt and block plus ``txlistinternal``."""
    if not isinstance(tx, dict) or not isinstance(receipt, dict) or not isinstance(block, dict):
        raise _bad("transaction not found or malformed")
    txid = tx.get("hash")
    if not isinstance(txid, str):
        raise _bad("missing transaction hash")
    when = datetime.fromtimestamp(_hex_int(block.get("timestamp"), "block timestamp"), tz=timezone.utc)
    gas_used = _hex_int(receipt.get("gasUsed"), "gas used")
    price = _hex_int(receipt.get("effectiveGasPrice", tx.get("gasPrice")), "gas price")
    data = tx.get("input")
    method = data[:10] if isinstance(data, str) and len(data) >= 10 else None
    children = tuple(
        Transaction(
            chain="ethereum",
            txid=txid,
            timestamp=when,
            inputs=(TxInput(_address(item.get("from")), _units(item.get("value", "0"), 18), None),),
            outputs=(TxOutput(_address(item.get("to")), _units(item.get("value", "0"), 18)),),
            source=NAME,
            kind="internal",
        )
        for item in unwrap_result(internal)
        if isinstance(item, dict)
    )
    return TransactionDetail(
        chain="ethereum",
        txid=txid,
        timestamp=when,
        block=_hex_int(tx.get("blockNumber"), "block number"),
        success=(receipt["status"] == "0x1") if receipt.get("status") in ("0x0", "0x1") else None,
        sender=_address(tx.get("from")),
        recipient=_address(tx.get("to")),
        value=_units(_hex_int(tx.get("value"), "value"), 18),
        fee=_units(gas_used * price, 18),
        gas_used=gas_used,
        method=method,
        internal=children,
        token_transfers=None,
        source=NAME,
    )


class EtherscanProvider:
    """Ethereum provider backed by the Etherscan API V2 (requires a free key)."""

    name = NAME
    chain = "ethereum"
    requires_key = KEY_VARIABLE

    def __init__(
        self,
        api_key: str | None,
        base_url: str = BASE_URL,
        client: httpx.Client | None = None,
        min_interval: float | None = None,
    ) -> None:
        if api_key is not None and not api_key:
            raise ValueError(f"{KEY_VARIABLE} must not be empty")
        # ``None`` means keyless use, for Etherscan-compatible open endpoints.
        self._key = api_key or ""
        # Pacing applies to real network use. An injected client (tests) is not paced.
        self._min_interval = min_interval if min_interval is not None else (MIN_INTERVAL if client is None else 0.0)
        self._last_call = 0.0
        self._http = HttpClient(NAME, base_url, secrets=(api_key,) if api_key else (), client=client)

    def _call(self, module: str, action: str, **params: Any) -> Any:
        wait = self._last_call + self._min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()
        query = {
            "chainid": CHAIN_ID,
            "module": module,
            "action": action,
            **params,
        }
        if self._key:
            query["apikey"] = self._key
        return self._http.get_json("/api", query)

    def _query(self, action: str, address: str, **extra: Any) -> Any:
        return self._call("account", action, address=address, **extra)

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

    def get_transaction(self, txid: str) -> TransactionDetail:
        """Return one transaction, its receipt, block time and internal transactions."""
        tx = unwrap_proxy(self._call("proxy", "eth_getTransactionByHash", txhash=txid))
        if tx is None:
            raise ProviderError(NAME, "transaction not found")
        receipt = unwrap_proxy(self._call("proxy", "eth_getTransactionReceipt", txhash=txid))
        block = unwrap_proxy(
            self._call("proxy", "eth_getBlockByNumber", tag=tx.get("blockNumber"), boolean="false")
        )
        internal = self._call("account", "txlistinternal", txhash=txid)
        return parse_transaction_detail(tx, receipt, block, internal)
