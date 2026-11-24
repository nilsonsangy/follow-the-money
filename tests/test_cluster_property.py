"""Property-based tests for cluster input classification.

Feature: walletexplorer-cluster-lookup, Property 1 and Property 2.

**Validates: Requirements 1.1, 2.1, 6.6**
"""
from __future__ import annotations

from hypothesis import given, settings, strategies as st

from follow_the_money.detect import (
    ADDRESS_PATTERNS,
    INPUT_ADDRESS,
    INPUT_TXID,
    classify_cluster_input,
)

_HEX = "0123456789abcdefABCDEF"
# Characters accepted after the prefix by the Bitcoin address pattern.
_BODY = "abcdefghijklmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ0123456789"
_BECH32_BODY = "abcdefghijklmnopqrstuvwxyz0123456789"


# Feature: walletexplorer-cluster-lookup, Property 1: a 64-hex string is
# always classified as a txid.
@settings(max_examples=5)
@given(st.text(alphabet=_HEX, min_size=64, max_size=64))
def test_property_1_txid_is_classified_as_txid(txid: str) -> None:
    assert classify_cluster_input(txid) == INPUT_TXID


@st.composite
def bitcoin_addresses(draw) -> str:
    prefix = draw(st.sampled_from(["1", "3", "bc1"]))
    alphabet = _BECH32_BODY if prefix == "bc1" else _BODY
    body = draw(st.text(alphabet=alphabet, min_size=25, max_size=39))
    return prefix + body


# Feature: walletexplorer-cluster-lookup, Property 2: a recognized Bitcoin
# address is classified as an address.
@settings(max_examples=5)
@given(bitcoin_addresses())
def test_property_2_bitcoin_address_is_classified_as_address(address: str) -> None:
    assert ADDRESS_PATTERNS["Bitcoin"].match(address)
    assert classify_cluster_input(address) == INPUT_ADDRESS


# ---------------------------------------------------------------------------
# Formatting properties (5-9).
#
# **Validates: Requirements 1.2, 1.3, 1.4, 1.5, 2.3, 2.4, 2.5, 5.2, 5.3, 5.4**
# ---------------------------------------------------------------------------
from follow_the_money.models import ClusterOutput, ClusterResult  # noqa: E402
from follow_the_money.report import format_cluster  # noqa: E402

_TEXT = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
    min_size=1,
    max_size=20,
)
_OPT_TEXT = st.one_of(st.none(), _TEXT)
_KIND = st.sampled_from(["address", "txid"])


@st.composite
def cluster_outputs(draw) -> ClusterOutput:
    return ClusterOutput(
        address=draw(_OPT_TEXT), wallet_id=draw(_OPT_TEXT), label=draw(_OPT_TEXT)
    )


@st.composite
def found_results(draw) -> ClusterResult:
    kind = draw(_KIND)
    outputs = tuple(draw(st.lists(cluster_outputs(), max_size=4))) if kind == "txid" else ()
    return ClusterResult(
        argument=draw(_TEXT),
        input_kind=kind,
        found=True,
        wallet_id=draw(_OPT_TEXT),
        label=draw(_OPT_TEXT),
        outputs=outputs,
    )


@st.composite
def missing_results(draw) -> ClusterResult:
    return ClusterResult(
        argument=draw(_TEXT),
        input_kind=draw(_KIND),
        found=False,
        wallet_id=None,
        label=None,
        outputs=(),
    )


def _has_prefix(lines: list[str], prefix: str) -> bool:
    return any(line.startswith(prefix) for line in lines)


# Feature: walletexplorer-cluster-lookup, Property 5: found=False yields a
# Result line and no Wallet, Label or Output lines.
@settings(max_examples=5)
@given(missing_results())
def test_property_5_missing_result_has_no_label_output(result: ClusterResult) -> None:
    lines = format_cluster(result)
    assert sum(line.startswith("Result: ") for line in lines) == 1
    for prefix in ("Label:", "Output:"):
        assert not _has_prefix(lines, prefix)
    assert lines[-1].startswith("Result: ")


# Feature: walletexplorer-cluster-lookup, Property 6: found=True always
# includes the Label line and the Wallet line when a wallet id exists.
@settings(max_examples=5)
@given(found_results())
def test_property_6_found_result_includes_label_only(result: ClusterResult) -> None:
    lines = format_cluster(result)
    for prefix in ("Query:", "Wallet:", "Source:", "Note:"):
        assert not _has_prefix(lines, prefix)
    expected = result.label if result.label is not None else "no known label"
    assert f"Label: {expected}" in lines
    assert not _has_prefix(lines, "Result:")


# Feature: walletexplorer-cluster-lookup, Property 7: txid outputs list
# address, wallet and label when present.
@settings(max_examples=5)
@given(found_results())
def test_property_7_outputs_carry_address_wallet_and_label(result: ClusterResult) -> None:
    lines = format_cluster(result)
    output_lines = [line for line in lines if line.startswith("Output: ")]
    expected = [out for out in result.outputs if out.wallet_id is not None]
    assert len(output_lines) == len(expected)
    for line, out in zip(output_lines, expected):
        origin = out.address if out.address is not None else "unknown address"
        assert origin in line
        assert f"wallet {out.wallet_id}" in line
        if out.label is not None:
            assert line.endswith(f"({out.label})")
        else:
            assert not line.endswith(")")


# Feature: walletexplorer-cluster-lookup, Property 8: Query, Wallet, Source and
# Note lines are never written.
@settings(max_examples=5)
@given(st.one_of(found_results(), missing_results()))
def test_property_8_no_query_wallet_source_or_note(result: ClusterResult) -> None:
    lines = format_cluster(result)
    for prefix in ("Query:", "Wallet:", "Source:", "Note:"):
        assert not _has_prefix(lines, prefix)


# Feature: walletexplorer-cluster-lookup, Property 9: formatting is
# deterministic and every line is a single line.
@settings(max_examples=5)
@given(st.one_of(found_results(), missing_results()))
def test_property_9_formatting_is_deterministic_and_line_based(result: ClusterResult) -> None:
    first = format_cluster(result)
    assert first == format_cluster(result)
    assert first[0] == f"Type: {result.input_kind}"
    assert all("\n" not in line for line in first)


# ---------------------------------------------------------------------------
# CLI error properties (3 and 4).
#
# **Validates: Requirements 4.1, 4.2**
# ---------------------------------------------------------------------------
import io  # noqa: E402

from follow_the_money.cli import main  # noqa: E402


class _FakeProvider:
    """Stands in for the WalletExplorer provider; must never be reached."""

    name = "walletexplorer.com"
    requires_key = None

    def lookup_address(self, address: str) -> ClusterResult:
        raise AssertionError("provider must not be called for rejected input")

    def lookup_tx(self, txid: str) -> ClusterResult:
        raise AssertionError("provider must not be called for rejected input")


def _run_cluster(argument: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = main(
        ["cluster", argument],
        stdout=out,
        stderr=err,
        env={},
        providers={"walletexplorer.com": _FakeProvider()},
    )
    return code, out.getvalue(), err.getvalue()


_BASE58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


@st.composite
def other_coin_addresses(draw) -> str:
    coin = draw(st.sampled_from(["Ethereum", "Litecoin", "Monero"]))
    if coin == "Ethereum":
        return "0x" + draw(st.text(alphabet=_HEX, min_size=40, max_size=40))
    if coin == "Litecoin":
        prefix = draw(st.sampled_from(["L", "M", "ltc1"]))
        alphabet = _BECH32_BODY if prefix == "ltc1" else _BODY
        return prefix + draw(st.text(alphabet=alphabet, min_size=25, max_size=39))
    return (
        draw(st.sampled_from(["4", "8"]))
        + draw(st.sampled_from(list("0123456789AB")))
        + draw(st.text(alphabet=_BASE58, min_size=93, max_size=93))
    )


# Feature: walletexplorer-cluster-lookup, Property 3: a recognized
# Ethereum, Litecoin or Monero address exits with 2 and a Bitcoin-only message.
@settings(max_examples=5)
@given(other_coin_addresses())
def test_property_3_other_coin_address_exits_2_with_bitcoin_only_message(address: str) -> None:
    code, out, err = _run_cluster(address)
    assert code == 2
    assert out == ""
    assert err.startswith("Error:")
    assert "WalletExplorer covers Bitcoin only" in err


# Feature: walletexplorer-cluster-lookup, Property 4: unrecognized input
# exits with 2 and an English error message.
@settings(max_examples=5)
@given(
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789 _-", max_size=30).map(
        lambda text: text + "!"  # "!" is outside every address and txid pattern
    )
)
def test_property_4_unrecognized_input_exits_2_with_error(text: str) -> None:
    code, out, err = _run_cluster(text)
    assert code == 2
    assert out == ""
    assert err.startswith("Error:")
    assert "Not a Bitcoin address or transaction id" in err
