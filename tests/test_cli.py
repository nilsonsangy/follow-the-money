"""CLI tests with fake providers: no network access."""

from __future__ import annotations

import io
from datetime import date, datetime, timezone
from decimal import Decimal

from follow_the_money.cli import main
from follow_the_money.errors import ProviderError
from follow_the_money.models import Balance, Transaction, TxInput, TxOutput

BTC_A = "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"
BTC_B = "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy"
ETH = "0x" + "ab" * 20
SECRET = "super-secret-key-123"


class FakeProvider:
    name = "fake"
    chain = "bitcoin"
    requires_key = None

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    def get_balance(self, address: str) -> Balance:
        if self.fail:
            raise ProviderError("fake", f"boom {SECRET}")
        return Balance(address, "bitcoin", Decimal("1.5"), "fake")

    def get_transactions(self, address: str, limit: int) -> list[Transaction]:
        if self.fail:
            raise ProviderError("fake", "boom")
        tx = Transaction(
            chain="bitcoin",
            txid="t1",
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            inputs=(TxInput(BTC_A, Decimal(1), None),),
            outputs=(TxOutput(BTC_B, Decimal(1)),),
            source="fake",
        )
        return [tx] if address == BTC_A else []

    def get_price(self, coin: str, on: date) -> Decimal:
        return Decimal(100)


def run(argv, **kwargs):
    out, err = io.StringIO(), io.StringIO()
    kwargs.setdefault("env", {})
    code = main(argv, stdout=out, stderr=err, **kwargs)
    return code, out.getvalue(), err.getvalue()


def test_input_errors_and_exit_codes():
    assert run(["detect", ETH])[:2] == (0, "Detected coin: Ethereum\n")
    code, _, err = run(["detect", "nope"])
    assert code == 2 and err.startswith("Error:")
    assert run(["trace", BTC_A, "--hops", "-1"])[0] == 2
    assert run(["history", BTC_A, "--limit", "0"])[0] == 2
    code, _, err = run(["balance", BTC_A, "--usd"], providers={"mempool.space": FakeProvider()})
    assert code == 1 and "COINGECKO_API_KEY" in err


def test_balance_with_usd_and_masked_provider_error():
    code, out, _ = run(
        ["balance", BTC_A, "--usd"],
        providers={"mempool.space": FakeProvider(), "coingecko": FakeProvider()},
        env={"COINGECKO_API_KEY": SECRET},
        today=date(2024, 1, 1),
    )
    assert code == 0 and "1.5 BTC" in out and "150.00 USD" in out
    code, _, err = run(
        ["balance", BTC_A],
        providers={"mempool.space": FakeProvider(fail=True)},
        env={"COINGECKO_API_KEY": SECRET},
    )
    assert code == 1 and SECRET not in err and "fake" in err

def test_history_trace_patterns_report(tmp_path):
    providers = {"mempool.space": FakeProvider()}
    assert "t1" in run(["history", BTC_A], providers=providers)[1]
    code, out, _ = run(["trace", BTC_A, "--hops", "1"], providers=providers)
    assert code == 0 and BTC_B in out
    assert run(["patterns", BTC_A], providers=providers)[0] == 0
    target = tmp_path / "r.md"
    code, _, _ = run(["report", BTC_A, "--out", str(target)], providers=providers)
    assert code == 0 and "| t1 |" in target.read_text(encoding="utf-8")
    first = run(["report", BTC_A], providers=providers)[1]
    assert first == run(["report", BTC_A], providers=providers)[1]


# --- Property-based test (hypothesis) ---
from hypothesis import given, strategies as st  # noqa: E402
from follow_the_money.detect import UNKNOWN, detect_coin  # noqa: E402

ADDRESS_COMMANDS = ["detect", "balance", "history", "trace", "patterns", "report"]
unknown_text = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)), max_size=60
).filter(lambda s: not s.startswith("-") and detect_coin(s) == UNKNOWN)


@given(
    text=unknown_text,
    command=st.sampled_from(ADDRESS_COMMANDS),
    address=st.sampled_from([BTC_A, BTC_B]),
    hops=st.integers(min_value=0, max_value=3),
)
def test_unrecognized_address_is_rejected_and_commands_are_deterministic(
    text, command, address, hops
):
    providers = {"mempool.space": FakeProvider()}
    code, out, err = run([command, text], providers=providers)
    assert code != 0
    assert out == ""
    assert err.startswith("Error:")
    assert err.replace(text.strip(), "").isascii()  # message wording is English

    argv = [command, address]
    if command in ("trace", "report"):
        argv += ["--hops", str(hops)]
    assert run(argv, providers=providers) == run(argv, providers=providers)
