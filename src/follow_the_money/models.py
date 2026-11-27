"""Immutable data models shared by providers, tracing, patterns and reports.

All monetary values are ``Decimal`` in the coin's own unit (BTC or ETH),
never floating point.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class TxInput:
    address: str | None
    value: Decimal
    prev_txid: str | None


@dataclass(frozen=True)
class TxOutput:
    address: str | None
    value: Decimal


@dataclass(frozen=True)
class Transaction:
    chain: str  # "bitcoin" | "ethereum"
    txid: str
    timestamp: datetime  # UTC
    inputs: tuple[TxInput, ...]
    outputs: tuple[TxOutput, ...]
    source: str  # provider name
    kind: str = "native"  # "native" | "token" | "internal" | "contract_call"


@dataclass(frozen=True)
class Evidence:
    txid: str
    timestamp: datetime
    source: str
    note: str


@dataclass(frozen=True)
class Balance:
    address: str
    chain: str
    amount: Decimal
    source: str


@dataclass(frozen=True)
class Finding:
    pattern: str
    txids: tuple[str, ...]
    detail: str


@dataclass(frozen=True)
class ClusterOutput:
    address: str | None
    wallet_id: str | None
    label: str | None


@dataclass(frozen=True)
class ClusterResult:
    argument: str  # the original argument, as typed
    input_kind: str  # "address" | "txid"
    found: bool
    wallet_id: str | None  # None when found is False
    label: str | None  # None when found is False or the wallet has no label
    outputs: tuple[ClusterOutput, ...]  # only populated for input_kind == "txid"
    source: str = "walletexplorer.com"


@dataclass(frozen=True)
class TransactionDetail:
    """One Ethereum transaction with the fields needed to confirm a finding.

    ``sender`` is the account that signed the transaction and paid the gas.
    ``internal`` holds the internal transactions produced by the execution.
    ``token_transfers`` is ``None`` when the provider does not report them for a
    single transaction, and a (possibly empty) tuple otherwise.
    """

    chain: str
    txid: str
    timestamp: datetime  # UTC
    block: int | None
    success: bool | None  # None when the receipt carries no status (before Byzantium)
    sender: str | None
    recipient: str | None  # None when the transaction creates a contract
    value: Decimal  # ETH
    fee: Decimal  # ETH actually paid (gas used x effective gas price)
    gas_used: int
    method: str | None
    internal: tuple[Transaction, ...]
    token_transfers: tuple[Transaction, ...] | None
    source: str
