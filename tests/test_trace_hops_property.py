"""Property-based tests for the hop limit of the funds trace.

Feature: crypto-tracing, Property 7: trace respects the hop limit.
**Validates: Requirements 9.6, 5.11**
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from decimal import Decimal

from hypothesis import given, strategies as st

from follow_the_money.models import Balance, Transaction, TxInput, TxOutput
from follow_the_money.trace import trace

MAX_NODES = 8


def addr(i: int) -> str:
    return f"0x{i:040x}"


class FakeProvider:
    """In-memory provider serving a synthetic graph of Ethereum addresses."""

    name = "fake"
    chain = "ethereum"
    requires_key = None

    def __init__(self, graph: dict[int, list[int]]) -> None:
        self.graph = graph

    def get_balance(self, address: str) -> Balance:
        return Balance(address, "ethereum", Decimal(0), self.name)

    def get_transactions(self, address: str, limit: int) -> list[Transaction]:
        index = int(address, 16)
        txs = [
            Transaction(
                chain="ethereum",
                txid=f"tx-{index}-{target}",
                timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
                inputs=(TxInput(addr(index), Decimal(1), None),),
                outputs=(TxOutput(addr(target), Decimal(1)),),
                source=self.name,
            )
            for target in self.graph.get(index, [])
        ]
        return txs[:limit]


@st.composite
def graphs(draw):
    n = draw(st.integers(min_value=1, max_value=MAX_NODES))
    graph = {
        i: draw(st.lists(st.integers(0, n - 1), max_size=n, unique=True))
        for i in range(n)
    }
    return graph


def reference_distances(
    graph: dict[int, list[int]], limit: int
) -> dict[int, int]:
    """Shortest distance from node 0 over the edges visible within ``limit``."""
    dist = {0: 0}
    queue = deque([0])
    while queue:
        cur = queue.popleft()
        for nxt in graph.get(cur, [])[:limit]:
            if nxt not in dist:
                dist[nxt] = dist[cur] + 1
                queue.append(nxt)
    return dist


@given(
    graph=graphs(),
    hops=st.integers(min_value=0, max_value=5),
    limit=st.integers(min_value=1, max_value=MAX_NODES),
)
def test_trace_respects_hop_limit(graph, hops, limit):
    result = trace(addr(0), FakeProvider(graph), hops=hops, limit=limit)
    expected = {
        addr(i): d
        for i, d in reference_distances(graph, limit).items()
        if d <= hops
    }

    # Every address in the result is within N hops.
    assert all(d <= hops for d in result.nodes.values())
    # Every address within N hops (inside the limit) is present, at its distance.
    assert result.nodes == expected

