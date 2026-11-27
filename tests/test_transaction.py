"""Example tests for the ``tx`` command and the provider ``get_transaction`` methods (no network)."""
from __future__ import annotations

import io
from decimal import Decimal

import httpx

from follow_the_money.cli import main
from follow_the_money.models import TransactionDetail
from follow_the_money.providers.blockscout import BlockscoutProvider
from follow_the_money.providers.etherscan import EtherscanProvider

HASH = "0x" + "ab" * 32
SENDER = "0x" + "11" * 20
RECEIVER = "0x" + "22" * 20
ATTACKER = "0x" + "33" * 20


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _blockscout_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/internal-transactions"):
        return httpx.Response(200, json={"items": [
            {"type": "call", "from": {"hash": RECEIVER}, "to": {"hash": ATTACKER}, "value": "2000000000000000000"}
        ]})
    if path.endswith("/token-transfers"):
        return httpx.Response(200, json={"items": []})
    return httpx.Response(200, json={
        "hash": HASH, "status": "ok", "result": "success", "block_number": 100,
        "timestamp": "2025-02-21T14:13:35.000000Z", "from": {"hash": SENDER}, "to": {"hash": RECEIVER},
        "value": "0", "fee": {"type": "actual", "value": "702240000000000"}, "gas_used": "70224",
        "method": "execTransaction",
    })


def _etherscan_handler(request: httpx.Request) -> httpx.Response:
    action = request.url.params["action"]
    if action == "eth_getTransactionByHash":
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {
            "hash": HASH, "blockNumber": "0x64", "from": SENDER, "to": RECEIVER, "value": "0x0",
            "gasPrice": "0x2540be400", "input": "0x6a76120200",
        }})
    if action == "eth_getTransactionReceipt":
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {
            "gasUsed": "0x11250", "effectiveGasPrice": "0x2540be400", "status": "0x1",
        }})
    if action == "eth_getBlockByNumber":
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"timestamp": "0x67b8a4af"}})
    return httpx.Response(200, json={"status": "1", "message": "OK", "result": [
        {"from": RECEIVER, "to": ATTACKER, "value": "2000000000000000000"}
    ]})


def test_blockscout_transaction_detail():
    detail = BlockscoutProvider(client=_client(_blockscout_handler)).get_transaction(HASH)
    assert detail.success and detail.sender == SENDER and detail.recipient == RECEIVER
    assert detail.fee == Decimal("0.00070224") and detail.gas_used == 70224
    assert detail.method == "execTransaction" and detail.token_transfers == ()
    assert [t.outputs[0].value for t in detail.internal] == [Decimal(2)]


def test_etherscan_transaction_detail():
    provider = EtherscanProvider("k" * 8, client=_client(_etherscan_handler))
    detail = provider.get_transaction(HASH)
    assert detail.success is True and detail.sender == SENDER.lower() and detail.block == 100
    assert detail.fee == Decimal("0.00070224") and detail.method == "0x6a761202"
    assert detail.token_transfers is None and len(detail.internal) == 1


class FakeDetailProvider:
    name = "fake"
    chain = "ethereum"
    requires_key = None

    def get_transaction(self, txid: str) -> TransactionDetail:
        return BlockscoutProvider(client=_client(_blockscout_handler)).get_transaction(txid)


def _run(argv, providers=None):
    out, err = io.StringIO(), io.StringIO()
    code = main(argv, env={}, providers=providers, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_tx_command_output_and_input_errors():
    code, out, _ = _run(["tx", HASH], providers={"blockscout": FakeDetailProvider()})
    assert code == 0
    assert f"From (signed and paid the gas): {SENDER}" in out
    assert "Fee paid: 0.00070224 ETH (gas used 70224)" in out
    assert f"{RECEIVER} -> {ATTACKER}  2" in out
    code, _, err = _run(["tx", "0x1234"])
    assert code == 2 and err.startswith("Error:")

def test_routescan_is_keyless_and_labels_its_source():
    from follow_the_money.providers.routescan import RoutescanProvider

    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        return _etherscan_handler(request)

    detail = RoutescanProvider(client=_client(handler)).get_transaction(HASH)
    assert detail.source == "routescan" and detail.internal[0].source == "routescan"
    assert all("apikey" not in params for params in seen)
