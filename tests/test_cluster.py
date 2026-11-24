"""Example tests for the WalletExplorer provider, using ``httpx.MockTransport`` (no network)."""
from __future__ import annotations

import httpx
import pytest

from follow_the_money.errors import ProviderError, RateLimitError
from follow_the_money.models import ClusterOutput
from follow_the_money.providers.walletexplorer import NAME, WalletExplorerProvider

ADDRESS = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
TXID = "a" * 64
WALLET = "9155adea5d855091"
OTHER_WALLET = "7a2f0c9e1b3d4f5a"


def _provider(routes: dict[str, object]) -> tuple[WalletExplorerProvider, list[httpx.Request]]:
    """Build a provider whose transport answers by endpoint name.

    A route value is a JSON-serializable body or a ``httpx.Response``.
    """
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        route = routes[request.url.path.rsplit("/", 1)[-1]]
        if isinstance(route, httpx.Response):
            return route
        return httpx.Response(200, json=route)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return WalletExplorerProvider(client=client), seen


def test_address_with_label():
    provider, seen = _provider(
        {
            "address-lookup": {"found": True, "wallet_id": WALLET},
            "wallet-addresses": {"found": True, "label": "Kraken.com"},
        }
    )
    result = provider.lookup_address(ADDRESS)
    assert (result.argument, result.input_kind, result.found) == (ADDRESS, "address", True)
    assert result.wallet_id == WALLET
    assert result.label == "Kraken.com"
    assert result.outputs == ()
    assert result.source == NAME
    assert seen[0].url.params["address"] == ADDRESS
    assert seen[1].url.params["wallet"] == WALLET
    assert seen[1].url.params["count"] == "0"


def test_address_without_label():
    provider, _ = _provider(
        {
            "address-lookup": {"found": True, "wallet_id": WALLET},
            "wallet-addresses": {"found": True},
        }
    )
    result = provider.lookup_address(ADDRESS)
    assert result.found is True
    assert result.wallet_id == WALLET
    assert result.label is None


def test_address_not_found():
    provider, seen = _provider({"address-lookup": {"found": False}})
    result = provider.lookup_address(ADDRESS)
    assert result.found is False
    assert result.wallet_id is None
    assert result.label is None
    assert len(seen) == 1


def test_txid_with_labeled_outputs():
    labels = {WALLET: "Kraken.com", OTHER_WALLET: None}
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        endpoint = request.url.path.rsplit("/", 1)[-1]
        if endpoint == "tx":
            return httpx.Response(
                200,
                json={
                    "found": True,
                    "wallet_id": WALLET,
                    "out": [
                        {"address": "1B2cQ3", "wallet_id": OTHER_WALLET},
                        {"address": "1A1zP1", "wallet_id": WALLET},
                        {"address": "1NoWallet"},
                        {"address": "1C3dR4", "wallet_id": WALLET},
                    ],
                },
            )
        label = labels[request.url.params["wallet"]]
        body = {"found": True, **({"label": label} if label else {})}
        return httpx.Response(200, json=body)

    provider = WalletExplorerProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    result = provider.lookup_tx(TXID)
    assert (result.argument, result.input_kind, result.found) == (TXID, "txid", True)
    assert result.wallet_id == WALLET
    assert result.label == "Kraken.com"
    assert result.outputs == (
        ClusterOutput("1B2cQ3", OTHER_WALLET, None),
        ClusterOutput("1A1zP1", WALLET, "Kraken.com"),
        ClusterOutput("1C3dR4", WALLET, "Kraken.com"),
    )
    # One label lookup per distinct wallet, not per output.
    label_requests = [r for r in seen if r.url.path.endswith("wallet-addresses")]
    assert sorted(r.url.params["wallet"] for r in label_requests) == sorted(
        [WALLET, OTHER_WALLET]
    )


def test_txid_not_found():
    provider, seen = _provider({"tx": {"found": False}})
    result = provider.lookup_tx(TXID)
    assert result.found is False
    assert result.wallet_id is None
    assert result.outputs == ()
    assert seen[0].url.params["txid"] == TXID
    assert len(seen) == 1


def test_http_429_raises_rate_limit_without_retry():
    provider, seen = _provider({"address-lookup": httpx.Response(429, json={})})
    with pytest.raises(RateLimitError) as info:
        provider.lookup_address(ADDRESS)
    assert NAME in str(info.value)
    assert len(seen) == 1


def test_error_field_raises_provider_error():
    provider, _ = _provider({"address-lookup": {"error": "invalid address"}})
    with pytest.raises(ProviderError) as info:
        provider.lookup_address(ADDRESS)
    assert info.value.provider == NAME
    assert "invalid address" in str(info.value)


def test_invalid_json_raises_provider_error():
    provider, _ = _provider({"tx": httpx.Response(200, content=b"not json")})
    with pytest.raises(ProviderError) as info:
        provider.lookup_tx(TXID)
    assert info.value.provider == NAME
    assert "invalid JSON" in str(info.value)


# --- End-to-end CLI tests with a fake provider (no network) ---
import io  # noqa: E402

from follow_the_money.cli import main  # noqa: E402
from follow_the_money.models import ClusterResult  # noqa: E402


class FakeWalletExplorer:
    name = NAME
    requires_key = None

    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def lookup_address(self, address: str) -> ClusterResult:
        self.calls.append(("address", address))
        if self.error:
            raise self.error
        return self.result

    def lookup_tx(self, txid: str) -> ClusterResult:
        self.calls.append(("txid", txid))
        if self.error:
            raise self.error
        return self.result


def _cli(argv, provider, env=None):
    out, err = io.StringIO(), io.StringIO()
    code = main(
        argv,
        stdout=out,
        stderr=err,
        env=env if env is not None else {},
        providers={NAME: provider},
    )
    return code, out.getvalue(), err.getvalue()


def _address_result(**overrides) -> ClusterResult:
    base = dict(
        argument=ADDRESS,
        input_kind="address",
        found=True,
        wallet_id=WALLET,
        label="Kraken.com",
        outputs=(),
    )
    base.update(overrides)
    return ClusterResult(**base)


def test_cli_address_lookup_prints_type_and_label():
    fake = FakeWalletExplorer(_address_result())
    code, out, err = _cli(["cluster", ADDRESS], fake)
    assert code == 0 and err == ""
    assert fake.calls == [("address", ADDRESS)]
    assert out.splitlines() == ["Type: address", "Label: Kraken.com"]


def test_cli_txid_lookup_prints_outputs():
    result = ClusterResult(
        argument=TXID,
        input_kind="txid",
        found=True,
        wallet_id=WALLET,
        label=None,
        outputs=(ClusterOutput("1B2cQ3", OTHER_WALLET, None),),
    )
    fake = FakeWalletExplorer(result)
    code, out, _ = _cli(["cluster", TXID.upper()], fake)
    assert code == 0
    assert fake.calls == [("txid", TXID.upper())]
    assert "1B2cQ3" in out and OTHER_WALLET in out


def test_cli_not_found_exits_zero():
    for argument, kind in ((ADDRESS, "address"), (TXID, "txid")):
        fake = FakeWalletExplorer(
            ClusterResult(argument, kind, False, None, None, ())
        )
        code, out, err = _cli(["cluster", argument], fake)
        assert code == 0 and err == ""
        expected = "no cluster found" if kind == "address" else "transaction not found"
        assert f"Result: {expected}" in out
        assert "Wallet:" not in out


def test_cli_rate_limit_and_provider_error_exit_one():
    code, out, err = _cli(["cluster", ADDRESS], FakeWalletExplorer(error=RateLimitError(NAME)))
    assert code == 1 and out == "" and NAME in err and err.startswith("Error:")
    code, out, err = _cli(
        ["cluster", TXID], FakeWalletExplorer(error=ProviderError(NAME, "service down"))
    )
    assert code == 1 and out == "" and "service down" in err


def test_cli_invalid_input_exits_two():
    fake = FakeWalletExplorer(_address_result())
    code, _, err = _cli(["cluster", "nope"], fake)
    assert code == 2 and err.startswith("Error:")
    code, _, err = _cli(["cluster", "0x" + "ab" * 20], fake)
    assert code == 2 and "Bitcoin only" in err
    assert fake.calls == []


def test_cli_output_is_deterministic():
    fake = FakeWalletExplorer(_address_result())
    assert _cli(["cluster", ADDRESS], fake) == _cli(["cluster", ADDRESS], fake)


def test_cli_ignores_provider_keys_from_env():
    keys = {
        "COINGECKO_API_KEY": "key-one-123456",
        "ETHERSCAN_API_KEY": "key-two-123456",
        "BLOCKCHAIR_API_KEY": "key-three-123456",
    }
    plain = _cli(["cluster", ADDRESS], FakeWalletExplorer(_address_result()))
    with_keys = _cli(["cluster", ADDRESS], FakeWalletExplorer(_address_result()), env=keys)
    assert with_keys == plain
    assert not any(value in with_keys[1] + with_keys[2] for value in keys.values())
