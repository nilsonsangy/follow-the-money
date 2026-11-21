"""Pure detectors for common fund-obfuscation and scam patterns.

Every detector takes a list of ``Transaction`` objects and returns a list of
``Finding`` objects. No detector performs I/O.

The thresholds below are **heuristics, not proof**. A finding is a lead for
further manual verification: legitimate activity can match these shapes, and
real obfuscation can be shaped to avoid them.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal

from .models import Finding, Transaction, TxOutput

# --- Peel chain heuristics -------------------------------------------------

#: Minimum number of chained transactions to report a peel chain.
PEEL_CHAIN_MIN_TRANSACTIONS = 3

#: A transaction is peel-shaped when its largest output is at least this many
#: times the sum of the remaining outputs ("peel" is the small remainder).
PEEL_MIN_LARGE_TO_SMALL_RATIO = Decimal(4)

# --- CoinJoin heuristics ---------------------------------------------------

#: Minimum number of outputs of a transaction to be a CoinJoin candidate.
COINJOIN_MIN_OUTPUTS = 5

#: Minimum number of outputs sharing exactly the same (non-zero) value.
COINJOIN_MIN_EQUAL_OUTPUTS = 3

# --- Address poisoning heuristics ------------------------------------------

#: Number of leading characters that must match a known counterparty.
POISONING_PREFIX_LENGTH = 4

#: Number of trailing characters that must match a known counterparty.
POISONING_SUFFIX_LENGTH = 4

#: Largest value, per chain, still considered "dust" for poisoning purposes.
#: Zero-value transfers always qualify. Values are in the coin's own unit.
POISONING_MAX_DUST_VALUE: dict[str, Decimal] = {
    "bitcoin": Decimal("0.00001"),
    "ethereum": Decimal("0.0001"),
}

_ZERO = Decimal(0)


def _output_total_for(tx: Transaction, address: str) -> Decimal:
    return sum((o.value for o in tx.outputs if o.address == address), _ZERO)


# --- Peel chain -------------------------------------------------------------


def _large_output(tx: Transaction) -> TxOutput | None:
    """Return the dominant output of a peel-shaped transaction, else ``None``."""
    if len(tx.inputs) != 1 or len(tx.outputs) < 2:
        return None
    ordered = sorted(tx.outputs, key=lambda o: o.value, reverse=True)
    large, rest = ordered[0], ordered[1:]
    if large.address is None or large.value <= _ZERO:
        return None
    if large.value == rest[0].value:
        return None  # no unique dominant output
    small_total = sum((o.value for o in rest), _ZERO)
    if small_total <= _ZERO:
        return None
    if large.value < PEEL_MIN_LARGE_TO_SMALL_RATIO * small_total:
        return None
    return large


def _feeds(prev: Transaction, large: TxOutput, nxt: Transaction) -> bool:
    """Whether ``nxt`` spends the large output of ``prev`` as its main input."""
    tx_input = nxt.inputs[0]
    if tx_input.prev_txid is not None:
        return tx_input.prev_txid == prev.txid and tx_input.address in (
            None,
            large.address,
        )
    return tx_input.address == large.address and nxt.timestamp > prev.timestamp


def detect_peel_chains(transactions: list[Transaction]) -> list[Finding]:
    """Find sequences of at least ``PEEL_CHAIN_MIN_TRANSACTIONS`` peel steps."""
    large_of: dict[str, TxOutput] = {}
    by_txid: dict[str, Transaction] = {}
    for tx in transactions:
        large = _large_output(tx)
        if large is not None and tx.txid not in by_txid:
            large_of[tx.txid] = large
            by_txid[tx.txid] = tx

    successor: dict[str, str] = {}
    has_predecessor: set[str] = set()
    for txid, tx in by_txid.items():
        for other_id, other in by_txid.items():
            if other_id == txid or other_id in has_predecessor:
                continue
            if _feeds(tx, large_of[txid], other):
                successor[txid] = other_id
                has_predecessor.add(other_id)
                break

    findings: list[Finding] = []
    for start in by_txid:
        if start in has_predecessor:
            continue
        chain = [start]
        seen = {start}
        while chain[-1] in successor and successor[chain[-1]] not in seen:
            chain.append(successor[chain[-1]])
            seen.add(chain[-1])
        if len(chain) >= PEEL_CHAIN_MIN_TRANSACTIONS:
            findings.append(
                Finding(
                    pattern="peel_chain",
                    txids=tuple(chain),
                    detail=(
                        f"{len(chain)} chained transactions, each forwarding a "
                        "large output and splitting off a small one (heuristic)"
                    ),
                )
            )
    return findings


# --- CoinJoin ---------------------------------------------------------------


def detect_coinjoin(transactions: list[Transaction]) -> list[Finding]:
    """Find transactions with many outputs, several of identical value."""
    findings: list[Finding] = []
    for tx in transactions:
        if len(tx.outputs) < COINJOIN_MIN_OUTPUTS:
            continue
        counts = Counter(o.value for o in tx.outputs if o.value > _ZERO)
        if not counts:
            continue
        value, equal = counts.most_common(1)[0]
        if equal >= COINJOIN_MIN_EQUAL_OUTPUTS:
            findings.append(
                Finding(
                    pattern="coinjoin",
                    txids=(tx.txid,),
                    detail=(
                        f"{len(tx.inputs)} inputs, {len(tx.outputs)} outputs, "
                        f"{equal} outputs of identical value {value} (heuristic)"
                    ),
                )
            )
    return findings


# --- Address poisoning --------------------------------------------------------


def _normalize(address: str) -> str:
    """Drop the ``0x`` marker and fold case for hexadecimal (Ethereum) addresses."""
    if address[:2].lower() == "0x":
        return address[2:].lower()
    return address


def _lookalike(a: str, b: str) -> bool:
    if a == b:
        return False
    na, nb = _normalize(a), _normalize(b)
    if na == nb:
        return False
    minimum = POISONING_PREFIX_LENGTH + POISONING_SUFFIX_LENGTH
    if len(na) < minimum or len(nb) < minimum:
        return False
    return (
        na[:POISONING_PREFIX_LENGTH] == nb[:POISONING_PREFIX_LENGTH]
        and na[-POISONING_SUFFIX_LENGTH:] == nb[-POISONING_SUFFIX_LENGTH:]
    )


def _is_dust(tx: Transaction, value: Decimal) -> bool:
    return value <= POISONING_MAX_DUST_VALUE.get(tx.chain, _ZERO)


def detect_address_poisoning(
    transactions: list[Transaction], victim: str
) -> list[Finding]:
    """Find dust transfers to ``victim`` from look-alike counterparty addresses.

    A look-alike sender shares the first and last characters with an address
    the victim interacted with earlier, but is not the same address.
    """
    findings: list[Finding] = []
    for tx in transactions:
        received = _output_total_for(tx, victim)
        if not any(o.address == victim for o in tx.outputs) or not _is_dust(
            tx, received
        ):
            continue
        senders = {i.address for i in tx.inputs if i.address and i.address != victim}
        for sender in sorted(senders):
            match = _find_known_lookalike(transactions, tx, victim, sender)
            if match is not None:
                known, known_txid = match
                findings.append(
                    Finding(
                        pattern="address_poisoning",
                        txids=(tx.txid, known_txid),
                        detail=(
                            f"{sender} mimics previously used address {known} "
                            f"(same first {POISONING_PREFIX_LENGTH} and last "
                            f"{POISONING_SUFFIX_LENGTH} characters) and sent "
                            f"{received} (heuristic)"
                        ),
                    )
                )
    return findings


def _find_known_lookalike(
    transactions: list[Transaction], poison: Transaction, victim: str, sender: str
) -> tuple[str, str] | None:
    """Return ``(known_address, txid)`` of an earlier non-dust counterparty."""
    for tx in sorted(transactions, key=lambda t: t.timestamp):
        if tx.txid == poison.txid or tx.timestamp >= poison.timestamp:
            continue
        sent_by_victim = any(i.address == victim for i in tx.inputs)
        to_victim = any(o.address == victim for o in tx.outputs)
        if sent_by_victim:
            candidates = [
                o.address
                for o in tx.outputs
                if o.address and o.address != victim and not _is_dust(tx, o.value)
            ]
        elif to_victim and not _is_dust(tx, _output_total_for(tx, victim)):
            candidates = [i.address for i in tx.inputs if i.address]
        else:
            continue
        for known in candidates:
            if _lookalike(sender, known):
                return known, tx.txid
    return None


def detect_patterns(
    transactions: list[Transaction], victim: str | None = None
) -> list[Finding]:
    """Run all detectors. Address poisoning runs only when ``victim`` is given."""
    findings = detect_peel_chains(transactions) + detect_coinjoin(transactions)
    if victim is not None:
        findings += detect_address_poisoning(transactions, victim)
    return findings
