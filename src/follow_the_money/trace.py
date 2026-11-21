"""Funds tracing: breadth-first search limited by hops.

Starting from one address, the search follows outgoing funds. An address is
a sender in a transaction when it appears among the transaction inputs, and
every output address of that transaction is a recipient. Recipients become the
next hop. Works for Bitcoin (UTXO, several inputs and outputs) and Ethereum
(account model, one input and one output per transfer).

The module is pure apart from the calls to the given provider.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .detect import detect_coin, normalize_address
from .errors import InvalidAddressError
from .providers.base import Provider

DEFAULT_HOPS = 3
DEFAULT_LIMIT = 25

_COIN_TO_CHAIN = {"Bitcoin": "bitcoin", "Ethereum": "ethereum"}


@dataclass(frozen=True)
class FundsEdge:
    """Funds that moved from one address to another in one transaction."""

    source: str
    target: str
    txid: str
    value: Decimal
    timestamp: datetime
    provider: str
    kind: str = "native"


@dataclass(frozen=True)
class FundsGraph:
    """Result of a trace.

    ``nodes`` maps each reached address to its distance (in hops) from
    ``origin``. ``edges`` are listed in discovery order.
    """

    origin: str
    chain: str
    hops: int
    nodes: dict[str, int]
    edges: tuple[FundsEdge, ...]


def _canonical(chain: str, address: str) -> str:
    """Canonical form of an address returned by a provider."""
    return normalize_address(address) if chain == "ethereum" else address.strip()


def trace(
    address: str,
    provider: Provider,
    hops: int = DEFAULT_HOPS,
    limit: int = DEFAULT_LIMIT,
) -> FundsGraph:
    """Trace outgoing funds from ``address`` up to ``hops`` hops.

    Args:
        address: Starting Bitcoin or Ethereum address.
        provider: Data source used to list the transactions of each address.
        hops: Maximum distance from the starting address (0 returns only it).
        limit: Maximum number of transactions requested per address.

    Raises:
        InvalidAddressError: The address is neither Bitcoin nor Ethereum.
        ValueError: ``hops`` is negative or ``limit`` is not positive.
    """
    if hops < 0:
        raise ValueError("hops must be zero or greater")
    if limit < 1:
        raise ValueError("limit must be at least 1")

    chain = _COIN_TO_CHAIN.get(detect_coin(address))
    if chain is None:
        raise InvalidAddressError(address)

    origin = _canonical(chain, normalize_address(address))
    nodes: dict[str, int] = {origin: 0}
    edges: list[FundsEdge] = []
    seen_edges: set[tuple[str, str, str, str]] = set()
    queue: deque[str] = deque([origin])

    while queue:
        current = queue.popleft()
        depth = nodes[current]
        if depth >= hops:
            continue

        for tx in provider.get_transactions(current, limit):
            senders = {
                _canonical(chain, i.address) for i in tx.inputs if i.address
            }
            if current not in senders:
                continue
            for out in tx.outputs:
                if not out.address:
                    continue
                target = _canonical(chain, out.address)
                if target == current:
                    continue
                key = (current, target, tx.txid, tx.kind)
                if key not in seen_edges:
                    seen_edges.add(key)
                    edges.append(
                        FundsEdge(
                            source=current,
                            target=target,
                            txid=tx.txid,
                            value=out.value,
                            timestamp=tx.timestamp,
                            provider=tx.source,
                            kind=tx.kind,
                        )
                    )
                if target not in nodes:
                    nodes[target] = depth + 1
                    queue.append(target)

    return FundsGraph(
        origin=origin, chain=chain, hops=hops, nodes=nodes, edges=tuple(edges)
    )
