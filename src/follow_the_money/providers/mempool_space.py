"""mempool.space provider (Bitcoin, open, no API key).

API reference: https://mempool.space/docs/api/rest
Amounts are returned in satoshis and converted to BTC as ``Decimal``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx

from ..errors import ProviderError
from ..models import Balance, Transaction, TxInput, TxOutput
from ._http import HttpClient

NAME = "mempool.space"
BASE_URL = "https://mempool.space/api"
SATOSHIS_PER_BTC = Decimal(100_000_000)
PAGE_SIZE = 25  # confirmed transactions per page, fixed by the API


def _bad(reason: str) -> ProviderError:
    return ProviderError(NAME, f"unexpected response: {reason}")


def _btc(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _bad("amount is not an integer number of satoshis")
    return Decimal(value) / SATOSHIS_PER_BTC


def parse_transaction(raw: dict[str, Any]) -> Transaction:
    """Normalize one confirmed mempool.space transaction object."""
    try:
        txid = raw["txid"]
        block_time = raw["status"]["block_time"]
        vin = raw["vin"]
        vout = raw["vout"]
        if not isinstance(txid, str) or not isinstance(vin, list) or not isinstance(vout, list):
            raise _bad("malformed transaction")
        timestamp = datetime.fromtimestamp(block_time, tz=timezone.utc)
        inputs = []
        for item in vin:
            prevout = item.get("prevout")  # null for coinbase inputs
            if prevout is None:
                inputs.append(TxInput(None, Decimal(0), None))
            else:
                inputs.append(
                    TxInput(
                        prevout.get("scriptpubkey_address"),
                        _btc(prevout["value"]),
                        item.get("txid"),
                    )
                )
        outputs = tuple(
            TxOutput(item.get("scriptpubkey_address"), _btc(item["value"])) for item in vout
        )
    except ProviderError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError, OSError):
        raise _bad("malformed transaction") from None
    return Transaction(
        chain="bitcoin",
        txid=txid,
        timestamp=timestamp,
        inputs=tuple(inputs),
        outputs=outputs,
        source=NAME,
        kind="native",
    )


def parse_transactions(raw: Any) -> list[Transaction]:
    """Normalize a list of transactions. Unconfirmed ones (no block time) are skipped."""
    if not isinstance(raw, list):
        raise _bad("expected a list of transactions")
    return [
        parse_transaction(item)
        for item in raw
        if isinstance(item, dict) and (item.get("status") or {}).get("confirmed")
    ]


def parse_balance(address: str, raw: Any) -> Balance:
    """Normalize the address statistics object into a confirmed balance."""
    try:
        stats = raw["chain_stats"]
        satoshis = stats["funded_txo_sum"] - stats["spent_txo_sum"]
    except (KeyError, TypeError):
        raise _bad("malformed address statistics") from None
    return Balance(address, "bitcoin", _btc(satoshis), NAME)


class MempoolSpaceProvider:
    """Open Bitcoin provider backed by the mempool.space REST API."""

    name = NAME
    chain = "bitcoin"
    requires_key = None

    def __init__(
        self, base_url: str = BASE_URL, client: httpx.Client | None = None
    ) -> None:
        self._http = HttpClient(NAME, base_url, client=client)

    def get_balance(self, address: str) -> Balance:
        return parse_balance(address, self._http.get_json(f"/address/{address}"))

    def get_transactions(self, address: str, limit: int) -> list[Transaction]:
        """Return up to ``limit`` confirmed transactions, newest first."""
        result: list[Transaction] = []
        after: str | None = None
        while len(result) < limit:
            path = f"/address/{address}/txs/chain"
            if after:
                path += f"/{after}"
            raw = self._http.get_json(path)
            page = parse_transactions(raw)
            result.extend(page)
            if len(raw) < PAGE_SIZE or not page:
                break
            after = page[-1].txid
        return result[:limit]
