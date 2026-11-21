"""Property-based tests for provider response normalization (one test per provider).

Feature: crypto-tracing, Property 6: well-formed synthetic responses are
normalized into transactions that keep txid, timestamp, inputs, outputs and
amounts, and whose ``source`` is the provider name.

**Validates: Requirements 9.4, 9.5, 9.14**
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from hypothesis import given, strategies as st

from follow_the_money.providers import blockscout, mempool_space

HEX = "0123456789abcdef"
txids = st.text(alphabet=HEX, min_size=64, max_size=64)
eth_addresses = st.text(alphabet=HEX, min_size=40, max_size=40).map(lambda s: "0x" + s)
btc_addresses = st.text(
    alphabet="123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz",
    min_size=26,
    max_size=34,
)
epoch_seconds = st.integers(min_value=1_230_768_000, max_value=4_102_444_800)
satoshis = st.integers(min_value=0, max_value=21_000_000 * 100_000_000)
wei_amounts = st.integers(min_value=0, max_value=10**30)


# --- mempool.space -------------------------------------------------------

@st.composite
def mempool_transactions(draw):
    n_in = draw(st.integers(min_value=1, max_value=4))
    n_out = draw(st.integers(min_value=1, max_value=4))
    vin = [
        {
            "txid": draw(txids),
            "prevout": {
                "scriptpubkey_address": draw(btc_addresses),
                "value": draw(satoshis),
            },
        }
        for _ in range(n_in)
    ]
    vout = [
        {"scriptpubkey_address": draw(btc_addresses), "value": draw(satoshis)}
        for _ in range(n_out)
    ]
    return {
        "txid": draw(txids),
        "status": {"confirmed": True, "block_time": draw(epoch_seconds)},
        "vin": vin,
        "vout": vout,
    }


def _case_mempool_space_parse_transaction_preserves_fields(raw):
    tx = mempool_space.parse_transaction(raw)

    assert tx.source == mempool_space.NAME
    assert tx.chain == "bitcoin"
    assert tx.txid == raw["txid"]
    assert tx.timestamp == datetime.fromtimestamp(raw["status"]["block_time"], tz=timezone.utc)
    assert [(i.address, i.value, i.prev_txid) for i in tx.inputs] == [
        (v["prevout"]["scriptpubkey_address"], Decimal(v["prevout"]["value"]) / 10**8, v["txid"])
        for v in raw["vin"]
    ]
    assert [(o.address, o.value) for o in tx.outputs] == [
        (v["scriptpubkey_address"], Decimal(v["value"]) / 10**8) for v in raw["vout"]
    ]


def _case_mempool_space_parse_transactions_keeps_order_and_source(items):
    result = mempool_space.parse_transactions(items)

    assert [t.txid for t in result] == [i["txid"] for i in items]
    assert all(t.source == mempool_space.NAME for t in result)


def _case_mempool_space_parse_balance(address, funded, spent):
    raw = {"chain_stats": {"funded_txo_sum": funded, "spent_txo_sum": spent}}
    balance = mempool_space.parse_balance(address, raw)

    assert balance.source == mempool_space.NAME
    assert balance.address == address
    assert balance.amount == Decimal(funded - spent) / 10**8


# --- Blockscout ----------------------------------------------------------

iso_timestamps = epoch_seconds.map(
    lambda s: datetime.fromtimestamp(s, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000000Z")
)


@st.composite
def blockscout_native(draw):
    return {
        "hash": draw(txids),
        "timestamp": draw(iso_timestamps),
        "from": {"hash": draw(eth_addresses)},
        "to": {"hash": draw(eth_addresses), "is_contract": False},
        "value": str(draw(wei_amounts)),
        "raw_input": "0x",
    }


@st.composite
def blockscout_token(draw):
    return {
        "transaction_hash": draw(txids),
        "timestamp": draw(iso_timestamps),
        "from": {"hash": draw(eth_addresses)},
        "to": {"hash": draw(eth_addresses)},
        "total": {
            "value": str(draw(wei_amounts)),
            "decimals": str(draw(st.integers(min_value=0, max_value=18))),
        },
        "token": {"decimals": "18"},
    }


@st.composite
def blockscout_internal(draw):
    return {
        "transaction_hash": draw(txids),
        "timestamp": draw(iso_timestamps),
        "from": {"hash": draw(eth_addresses)},
        "to": {"hash": draw(eth_addresses)},
        "value": str(draw(wei_amounts)),
    }


def _check_blockscout(raw, tx, txid_key, value, kind):
    assert tx.source == blockscout.NAME
    assert tx.chain == "ethereum"
    assert tx.kind == kind
    assert tx.txid == raw[txid_key]
    assert tx.timestamp == datetime.fromisoformat(raw["timestamp"].replace("Z", "+00:00"))
    assert [(i.address, i.value) for i in tx.inputs] == [(raw["from"]["hash"], value)]
    assert [(o.address, o.value) for o in tx.outputs] == [(raw["to"]["hash"], value)]


def _case_blockscout_native_transaction_preserves_fields(raw):
    tx = blockscout.parse_native_transaction(raw)
    _check_blockscout(raw, tx, "hash", Decimal(raw["value"]) / 10**18, "native")


def _case_blockscout_token_transfer_preserves_fields(raw):
    tx = blockscout.parse_token_transfer(raw)
    value = Decimal(raw["total"]["value"]) / Decimal(10) ** int(raw["total"]["decimals"])
    _check_blockscout(raw, tx, "transaction_hash", value, "token")


def _case_blockscout_internal_transaction_preserves_fields(raw):
    tx = blockscout.parse_internal_transaction(raw)
    _check_blockscout(raw, tx, "transaction_hash", Decimal(raw["value"]) / 10**18, "internal")


def _case_blockscout_parse_items_keeps_order_and_source(items):
    result = blockscout.parse_items({"items": items}, blockscout.parse_native_transaction)

    assert [t.txid for t in result] == [i["hash"] for i in items]
    assert all(t.source == blockscout.NAME for t in result)


# --- Etherscan -----------------------------------------------------------

from follow_the_money.providers import etherscan  # noqa: E402


@st.composite
def etherscan_native(draw):
    return {
        "hash": draw(txids),
        "timeStamp": str(draw(epoch_seconds)),
        "from": draw(eth_addresses),
        "to": draw(eth_addresses),
        "value": str(draw(wei_amounts)),
        "input": "0x",
    }


@st.composite
def etherscan_token(draw):
    raw = draw(etherscan_native())
    raw["tokenDecimal"] = str(draw(st.integers(min_value=0, max_value=18)))
    return raw


def _check_etherscan(raw, tx, value, kind):
    assert tx.source == etherscan.NAME
    assert tx.chain == "ethereum"
    assert tx.kind == kind
    assert tx.txid == raw["hash"]
    assert tx.timestamp == datetime.fromtimestamp(int(raw["timeStamp"]), tz=timezone.utc)
    assert [(i.address, i.value) for i in tx.inputs] == [(raw["from"], value)]
    assert [(o.address, o.value) for o in tx.outputs] == [(raw["to"], value)]


def _case_etherscan_native_transaction_preserves_fields(raw):
    tx = etherscan.parse_native_transaction(raw)
    _check_etherscan(raw, tx, Decimal(raw["value"]) / 10**18, "native")


def _case_etherscan_contract_call_is_flagged(raw):
    raw["input"] = "0xa9059cbb"
    assert etherscan.parse_native_transaction(raw).kind == "contract_call"


def _case_etherscan_token_transfer_preserves_fields(raw):
    tx = etherscan.parse_token_transfer(raw)
    value = Decimal(raw["value"]) / Decimal(10) ** int(raw["tokenDecimal"])
    _check_etherscan(raw, tx, value, "token")


def _case_etherscan_internal_transaction_preserves_fields(raw):
    tx = etherscan.parse_internal_transaction(raw)
    _check_etherscan(raw, tx, Decimal(raw["value"]) / 10**18, "internal")


def _case_etherscan_parse_list_keeps_order_and_source(items):
    envelope = {"status": "1" if items else "0", "message": "OK", "result": items}
    result = etherscan.parse_list(envelope, etherscan.parse_native_transaction)

    assert [t.txid for t in result] == [i["hash"] for i in items]
    assert all(t.source == etherscan.NAME for t in result)


def _case_etherscan_parse_balance(address, wei):
    balance = etherscan.parse_balance(address, {"status": "1", "message": "OK", "result": str(wei)})

    assert balance.source == etherscan.NAME
    assert balance.address == address
    assert balance.amount == Decimal(wei) / 10**18


# --- Blockchair ----------------------------------------------------------

from follow_the_money.providers import blockchair  # noqa: E402

blockchair_times = epoch_seconds.map(
    lambda s: datetime.fromtimestamp(s, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
)


@st.composite
def blockchair_entries(draw):
    n_in = draw(st.integers(min_value=1, max_value=4))
    n_out = draw(st.integers(min_value=1, max_value=4))
    return {
        "transaction": {"hash": draw(txids), "time": draw(blockchair_times)},
        "inputs": [
            {
                "recipient": draw(btc_addresses),
                "value": draw(satoshis),
                "transaction_hash": draw(txids),
            }
            for _ in range(n_in)
        ],
        "outputs": [
            {"recipient": draw(btc_addresses), "value": draw(satoshis)} for _ in range(n_out)
        ],
    }


def _case_blockchair_parse_transaction_preserves_fields(entry):
    tx = blockchair.parse_transaction(entry)

    assert tx.source == blockchair.NAME
    assert tx.chain == "bitcoin"
    assert tx.txid == entry["transaction"]["hash"]
    assert tx.timestamp == datetime.strptime(
        entry["transaction"]["time"], "%Y-%m-%d %H:%M:%S"
    ).replace(tzinfo=timezone.utc)
    assert [(i.address, i.value, i.prev_txid) for i in tx.inputs] == [
        (v["recipient"], Decimal(v["value"]) / 10**8, v["transaction_hash"])
        for v in entry["inputs"]
    ]
    assert [(o.address, o.value) for o in tx.outputs] == [
        (v["recipient"], Decimal(v["value"]) / 10**8) for v in entry["outputs"]
    ]


def _case_blockchair_parse_transactions_keeps_order_and_source(entries):
    raw = {"data": {e["transaction"]["hash"]: e for e in entries}}
    result = blockchair.parse_transactions(raw)

    assert [t.txid for t in result] == [e["transaction"]["hash"] for e in entries]
    assert all(t.source == blockchair.NAME for t in result)


def _case_blockchair_parse_address_dashboard(address, sats, hashes):
    raw = {"data": {address: {"address": {"balance": sats}, "transactions": hashes}}}
    balance, listed = blockchair.parse_address_dashboard(address, raw)

    assert balance.source == blockchair.NAME
    assert balance.address == address
    assert balance.amount == Decimal(sats) / 10**8
    assert listed == hashes


# --- One test per provider -----------------------------------------------
@given(st.data())
def test_mempool_space_normalization(data):
    _case_mempool_space_parse_transaction_preserves_fields(data.draw(mempool_transactions()))
    _case_mempool_space_parse_transactions_keeps_order_and_source(
        data.draw(st.lists(mempool_transactions(), max_size=5))
    )
    _case_mempool_space_parse_balance(data.draw(btc_addresses), data.draw(satoshis), data.draw(satoshis))


@given(st.data())
def test_blockscout_normalization(data):
    _case_blockscout_native_transaction_preserves_fields(data.draw(blockscout_native()))
    _case_blockscout_token_transfer_preserves_fields(data.draw(blockscout_token()))
    _case_blockscout_internal_transaction_preserves_fields(data.draw(blockscout_internal()))
    _case_blockscout_parse_items_keeps_order_and_source(
        data.draw(st.lists(blockscout_native(), max_size=5))
    )


@given(st.data())
def test_etherscan_normalization(data):
    _case_etherscan_native_transaction_preserves_fields(data.draw(etherscan_native()))
    _case_etherscan_contract_call_is_flagged(data.draw(etherscan_native()))
    _case_etherscan_token_transfer_preserves_fields(data.draw(etherscan_token()))
    _case_etherscan_internal_transaction_preserves_fields(data.draw(etherscan_native()))
    _case_etherscan_parse_list_keeps_order_and_source(
        data.draw(st.lists(etherscan_native(), max_size=5))
    )
    _case_etherscan_parse_balance(data.draw(eth_addresses), data.draw(wei_amounts))


@given(st.data())
def test_blockchair_normalization(data):
    _case_blockchair_parse_transaction_preserves_fields(data.draw(blockchair_entries()))
    _case_blockchair_parse_transactions_keeps_order_and_source(
        data.draw(
            st.lists(blockchair_entries(), max_size=5, unique_by=lambda e: e["transaction"]["hash"])
        )
    )
    _case_blockchair_parse_address_dashboard(
        data.draw(btc_addresses), data.draw(satoshis), data.draw(st.lists(txids, max_size=5))
    )
