"""WalletExplorer provider (Bitcoin only, open, no API key).

API reference: https://www.walletexplorer.com/api
Every response carries either ``found`` (boolean) or ``error`` (text).
"""

from __future__ import annotations

from typing import Any

import httpx

from ..errors import ProviderError
from ..models import ClusterOutput, ClusterResult
from ._http import HttpClient

NAME = "walletexplorer.com"
BASE_URL = "https://www.walletexplorer.com/api/1"


def _bad(reason: str) -> ProviderError:
    return ProviderError(NAME, f"unexpected response: {reason}")


def _optional_text(value: Any) -> str | None:
    """Return ``value`` when it is a non-empty string, otherwise ``None``."""
    return value if isinstance(value, str) and value else None


class WalletExplorerProvider:
    """Looks up the wallet cluster of a Bitcoin address or transaction."""

    name = NAME
    requires_key = None

    def __init__(self, base_url: str = BASE_URL, client: httpx.Client | None = None) -> None:
        self._http = HttpClient(NAME, base_url, client=client)

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        data = self._http.get_json(path, params)
        if not isinstance(data, dict):
            raise _bad("response is not a JSON object")
        if "error" in data:
            raise ProviderError(NAME, str(data["error"]))
        if not isinstance(data.get("found"), bool):
            raise _bad("missing 'found' field")
        return data

    def lookup_address(self, address: str) -> ClusterResult:
        data = self._get("address-lookup", {"address": address})
        if not data["found"]:
            return ClusterResult(address, "address", False, None, None, ())
        wallet_id = _optional_text(data.get("wallet_id"))
        if wallet_id is None:
            raise _bad("missing 'wallet_id' field")
        return ClusterResult(
            address, "address", True, wallet_id, self._label_for(wallet_id), ()
        )

    def lookup_tx(self, txid: str) -> ClusterResult:
        data = self._get("tx", {"txid": txid})
        if not data["found"]:
            return ClusterResult(txid, "txid", False, None, None, ())
        raw_outputs = data.get("out", [])
        if not isinstance(raw_outputs, list):
            raise _bad("'out' is not a list")
        labels: dict[str, str | None] = {}

        def label_of(wallet_id: str) -> str | None:
            if wallet_id not in labels:
                labels[wallet_id] = self._label_for(wallet_id)
            return labels[wallet_id]

        wallet_id = _optional_text(data.get("wallet_id"))
        outputs: list[ClusterOutput] = []
        for item in raw_outputs:
            if not isinstance(item, dict):
                raise _bad("malformed output")
            output_wallet = _optional_text(item.get("wallet_id"))
            if output_wallet is None:
                continue
            outputs.append(
                ClusterOutput(
                    _optional_text(item.get("address")),
                    output_wallet,
                    label_of(output_wallet),
                )
            )
        label = label_of(wallet_id) if wallet_id else None
        return ClusterResult(txid, "txid", True, wallet_id, label, tuple(outputs))

    def _label_for(self, wallet_id: str) -> str | None:
        """Return the wallet label, or ``None`` when the wallet has no known name."""
        data = self._get("wallet-addresses", {"wallet": wallet_id, "from": 0, "count": 0})
        if not data["found"]:
            return None
        return _optional_text(data.get("label"))
