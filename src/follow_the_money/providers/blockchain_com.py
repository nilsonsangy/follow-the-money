"""Blockchain.com provider (Bitcoin, API key optional).

API reference: https://www.blockchain.com/explorer/docs (Explorer API).
Uses ``POST /btc/address`` for the balance and ``POST /btc/address/transactions``
for the transaction list. Requests without a key use the default limits of the
service; a key, sent in the ``X-Explorer-Auth-Key`` header, applies the limits
of the account plan. Amounts are returned in satoshis and converted to BTC as
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

NAME = "blockchain.com"
BASE_URL = "https://api.blockchain.info/explorer-gateway-kt"
KEY_VARIABLE = "BLOCKCHAIN_API_KEY"
KEY_HEADER = "X-Explorer-Auth-Key"
SATOSHIS_PER_BTC = Decimal(100_000_000)
PAGE_SIZE = 50  # maximum ``limit`` accepted by the API


def _bad(reason: str) -> ProviderError:
    return ProviderError(NAME, f"unexpected response: {reason}")


def _btc(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _bad("amount is not an integer number of satoshis")
    return Decimal(value) / SATOSHIS_PER_BTC


def parse_transaction(raw: dict[str, Any]) -> Transaction:
    """Normalize one confirmed transaction of the Explorer API."""
    try:
        txid = raw["txId"]
        vin = raw["inputs"]
        vout = raw["outputs"]
        if not isinstance(txid, str) or not isinstance(vin, list) or not isinstance(vout, list):
            raise _bad("malformed transaction")
        timestamp = datetime.fromtimestamp(raw["time"], tz=timezone.utc)
        inputs = tuple(
            TxInput(None, Decimal(0), None)
            if item.get("coinbase")
            else TxInput(item.get("address"), _btc(item["value"]), item.get("txid"))
            for item in vin
        )
        outputs = tuple(TxOutput(item.get("address"), _btc(item["value"])) for item in vout)
    except ProviderError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError, OSError):
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
    """Normalize a transaction page. Mempool (unconfirmed) entries are skipped."""
    if not isinstance(raw, dict) or not isinstance(raw.get("transactions"), list):
        raise _bad("missing 'transactions'")
    return [
        parse_transaction(item)
        for item in raw["transactions"]
        if isinstance(item, dict) and not item.get("mempool")
    ]


def parse_balance(address: str, raw: Any) -> Balance:
    """Normalize the address object into a confirmed balance."""
    try:
        satoshis = raw["confirmed"]
    except (KeyError, TypeError):
        raise _bad("malformed address object") from None
    return Balance(address, "bitcoin", _btc(satoshis), NAME)


class BlockchainComProvider:
    """Bitcoin provider backed by the Blockchain.com Explorer API."""

    name = NAME
    chain = "bitcoin"
    requires_key = None  # the key is optional

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = BASE_URL,
        client: httpx.Client | None = None,
    ) -> None:
        headers = {KEY_HEADER: api_key} if api_key else {}
        self._http = HttpClient(
            NAME, base_url, secrets=(api_key,), headers=headers, client=client
        )

    def get_balance(self, address: str) -> Balance:
        return parse_balance(address, self._http.post_json("/btc/address", {"address": address}))

    def get_transactions(self, address: str, limit: int) -> list[Transaction]:
        """Return up to ``limit`` confirmed transactions, newest first."""
        result: list[Transaction] = []
        offset = 0
        while len(result) < limit:
            size = min(PAGE_SIZE, limit - len(result))
            raw = self._http.post_json(
                "/btc/address/transactions",
                {"address": address, "limit": size, "offset": offset},
            )
            page = parse_transactions(raw)
            result.extend(page)
            fetched = len(raw["transactions"])
            if fetched < size:
                break
            offset += fetched
        result.sort(key=lambda tx: tx.timestamp, reverse=True)
        return result[:limit]