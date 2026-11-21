"""Property-based tests for pattern detection.

Feature: crypto-tracing, Property 8: injected patterns are reported citing the
injected txids; lists with no pattern and no accidental coincidence yield no
findings.

**Validates: Requirements 9.7, 9.14**
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from hypothesis import given, strategies as st

from follow_the_money.models import Transaction, TxInput, TxOutput
from follow_the_money.patterns import detect_patterns

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _ts(n: int) -> datetime:
    return T0 + timedelta(minutes=n)


def _tx(chain, txid, n, inputs, outputs) -> Transaction:
    return Transaction(chain, txid, _ts(n), tuple(inputs), tuple(outputs), "test")


# Benign transactions: unique addresses, at most 4 outputs, outputs in [1, 3]
# so no output dominates (ratio < 4) and there is no CoinJoin shape.
@st.composite
def benign_transactions(draw):
    count = draw(st.integers(min_value=0, max_value=8))
    txs = []
    for i in range(count):
        values = draw(
            st.lists(st.integers(min_value=100, max_value=300), min_size=1, max_size=4)
        )
        txs.append(
            _tx(
                "bitcoin",
                f"benign{i}",
                i,
                [TxInput(f"in{i}", Decimal(sum(values)) / 100, None)],
                [TxOutput(f"out{i}_{j}", Decimal(v) / 100) for j, v in enumerate(values)],
            )
        )
    return txs


hex4 = st.text(alphabet="0123456789abcdef", min_size=4, max_size=4)
hex32 = st.text(alphabet="0123456789abcdef", min_size=32, max_size=32)


@given(benign_transactions(), st.booleans())
def test_no_pattern_no_findings(txs, with_victim):
    victim = "in0" if with_victim else None
    assert detect_patterns(txs, victim) == []


@given(
    noise=benign_transactions(),
    length=st.integers(min_value=3, max_value=8),
    small=st.integers(min_value=1, max_value=5),
    equal=st.integers(min_value=3, max_value=6),
    head=hex4,
    tail=hex4,
    mid1=hex32,
    mid2=hex32,
    zero=st.booleans(),
)
def test_injected_patterns_are_reported(noise, length, small, equal, head, tail, mid1, mid2, zero):
    # Peel chain
    chain = [
        _tx(
            "bitcoin",
            f"peel{i}",
            100 + i,
            [TxInput(f"peeladdr{i}", Decimal(100 + small), f"peel{i - 1}" if i else None)],
            [TxOutput(f"peeladdr{i + 1}", Decimal(100)), TxOutput(f"peelsmall{i}", Decimal(small))],
        )
        for i in range(length)
    ]
    peel = [f for f in detect_patterns(noise + chain) if f.pattern == "peel_chain"]
    injected = {t.txid for t in chain}
    assert any(injected <= set(f.txids) for f in peel)
    assert all(set(f.txids) <= injected for f in peel)

    # CoinJoin
    outputs = [TxOutput(f"cj_equal{i}", Decimal("0.5")) for i in range(equal)]
    outputs += [TxOutput(f"cj_other{i}", Decimal(i + 1) / 7) for i in range(3)]
    inputs = [TxInput(f"cj_in{i}", Decimal(1), None) for i in range(equal)]
    cj = _tx("bitcoin", "coinjoin0", 200, inputs, outputs)
    findings = detect_patterns(noise + [cj])
    assert any(f.pattern == "coinjoin" and f.txids == ("coinjoin0",) for f in findings)

    # Address poisoning
    known = "0x" + head + mid1 + tail
    fake = "0x" + head + mid2 + tail
    victim = "0x" + "ab" * 20
    if known == fake or victim in (known, fake):
        return
    legit = _tx("ethereum", "legit0", 300, [TxInput(victim, Decimal(1), None)], [TxOutput(known, Decimal(1))])
    dust = Decimal(0) if zero else Decimal("0.00001")
    poison = _tx("ethereum", "poison0", 400, [TxInput(fake, dust, None)], [TxOutput(victim, dust)])
    findings = detect_patterns(noise + [legit, poison], victim)
    assert any(
        f.pattern == "address_poisoning" and set(f.txids) == {"poison0", "legit0"}
        for f in findings
    )
