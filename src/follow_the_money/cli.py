"""Command-line entry point for the `ftm` command.

Exit codes:

- ``0``: success.
- ``1``: provider or configuration failure (network error, rate limit, missing key).
- ``2``: invalid input (unrecognized address, bad option value, unsupported coin).

Every message is in English and passes through ``mask_secrets`` before being
written, so API key values never reach the output.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, TextIO

from . import config
from .detect import (
    INPUT_ADDRESS,
    INPUT_UNKNOWN,
    UNKNOWN,
    classify_cluster_input,
    detect_coin,
    is_ethereum_tx_hash,
    normalize_address,
)
from .errors import InvalidAddressError, MissingKeyError, ProviderError
from .masking import mask_secrets
from .models import Evidence, Transaction, TransactionDetail
from .patterns import detect_patterns
from .pricing import to_usd
from .report import format_cluster, format_timestamp, render_report
from .trace import DEFAULT_HOPS, DEFAULT_LIMIT, FundsGraph, trace

EXIT_OK = 0
EXIT_PROVIDER = 1
EXIT_INPUT = 2

_KEY_VARIABLES = ("ETHERSCAN_API_KEY", "BLOCKCHAIN_API_KEY", "COINGECKO_API_KEY")
_PROVIDER_CHOICES = ("mempool.space", "blockscout", "etherscan", "blockchain.com", "routescan")
_COIN_TO_CHAIN = {"Bitcoin": "bitcoin", "Ethereum": "ethereum"}
_UNIT = {"bitcoin": "BTC", "ethereum": "ETH"}
_PROVIDER_HELP = "data provider to query (default: the open provider of the chain)"
_LIMIT_HELP = f"maximum number of transactions to fetch (default: {DEFAULT_LIMIT})"
_HOPS_HELP = f"maximum distance from the origin address, in hops (default: {DEFAULT_HOPS})"
_ADDRESS_HELP = "Bitcoin or Ethereum address"
_DETECT_ADDRESS_HELP = "wallet address of Bitcoin, Ethereum, Litecoin or Monero (the coin is detected from the format)"


class _InputError(Exception):
    """Invalid user input, reported with exit code 2."""


def _non_negative(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid integer: {text!r}") from None
    if value < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return value


def _positive(text: str) -> int:
    value = _non_negative(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


class AlphabeticalHelpFormatter(argparse.HelpFormatter):
    """Help formatter with a predictable order.

    ``-h/--help`` comes first, positional arguments keep the order of use,
    options are sorted by long name without dashes, and subcommands are sorted
    by name. Only the display order changes; parsing is untouched.
    """

    @staticmethod
    def _long_name(action: argparse.Action) -> str:
        long = next(
            (s for s in action.option_strings if s.startswith("--")),
            action.option_strings[0],
        )
        return long.lstrip("-")

    def add_arguments(self, actions: Any) -> None:
        actions = list(actions)
        positionals = [a for a in actions if not a.option_strings]
        options = [a for a in actions if a.option_strings]
        help_actions = [a for a in options if "-h" in a.option_strings]
        rest = sorted(
            (a for a in options if a not in help_actions), key=self._long_name
        )
        super().add_arguments(positionals + help_actions + rest)

    def _iter_indented_subactions(self, action: argparse.Action) -> Any:
        try:
            subactions = action._get_subactions()
        except AttributeError:
            return
        self._indent()
        yield from sorted(subactions, key=lambda a: str(a.metavar or a.dest))
        self._dedent()


def build_parser() -> argparse.ArgumentParser:
    """Build the parser with every command."""
    parser = argparse.ArgumentParser(
        prog="ftm",
        formatter_class=AlphabeticalHelpFormatter,
        description="Cryptocurrency address detection, balance, history, tracing and pattern analysis.",
    )
    commands = parser.add_subparsers(
        dest="command", required=True, metavar="COMMAND", help="command to run"
    )

    def add_command(name: str, *, help: str) -> argparse.ArgumentParser:
        """Add a subcommand whose description repeats its one-line help."""
        return commands.add_parser(
            name, help=help, description=help[0].upper() + help[1:] + ".",
            formatter_class=AlphabeticalHelpFormatter,
        )

    detect = add_command("detect", help="detect the coin of an address")
    detect.add_argument("address", help=_DETECT_ADDRESS_HELP)

    balance = add_command("balance", help="show the balance of an address")
    balance.add_argument("address", help=_ADDRESS_HELP)
    balance.add_argument("--provider", choices=_PROVIDER_CHOICES, help=_PROVIDER_HELP)
    balance.add_argument(
        "--usd", action="store_true", help="also show the value in US dollars at today's price"
    )

    history = add_command("history", help="list recent transactions, newest first")
    history.add_argument("address", help=_ADDRESS_HELP)
    history.add_argument("--limit", type=_positive, default=DEFAULT_LIMIT, help=_LIMIT_HELP)
    history.add_argument("--provider", choices=_PROVIDER_CHOICES, help=_PROVIDER_HELP)

    trace_cmd = add_command("trace", help="trace outgoing funds up to N hops")
    trace_cmd.add_argument("address", help=_ADDRESS_HELP)
    trace_cmd.add_argument("--hops", type=_non_negative, default=DEFAULT_HOPS, help=_HOPS_HELP)
    trace_cmd.add_argument("--limit", type=_positive, default=DEFAULT_LIMIT, help=_LIMIT_HELP)
    trace_cmd.add_argument("--provider", choices=_PROVIDER_CHOICES, help=_PROVIDER_HELP)

    patterns = add_command(
        "patterns", help="look for peel chains, CoinJoin and address poisoning"
    )
    patterns.add_argument("address", help=_ADDRESS_HELP)
    patterns.add_argument("--limit", type=_positive, default=DEFAULT_LIMIT, help=_LIMIT_HELP)
    patterns.add_argument("--provider", choices=_PROVIDER_CHOICES, help=_PROVIDER_HELP)

    report = add_command("report", help="write a Markdown trace report")
    report.add_argument("address", help=_ADDRESS_HELP)
    report.add_argument("--hops", type=_non_negative, default=DEFAULT_HOPS, help=_HOPS_HELP)
    report.add_argument("--out", metavar="FILE", help="write the report to this file instead of stdout")
    report.add_argument("--provider", choices=_PROVIDER_CHOICES, help=_PROVIDER_HELP)
    tx = add_command(
        "tx", help="show one Ethereum transaction: gas payer, fee and internal transfers"
    )
    tx.add_argument("hash", help="Ethereum transaction hash (0x followed by 64 hexadecimal characters)")
    tx.add_argument("--provider", choices=_PROVIDER_CHOICES, help=_PROVIDER_HELP)
    cluster = add_command(
        "cluster", help="look up the wallet cluster of a Bitcoin address or transaction id"
    )
    cluster.add_argument(
        "argument",
        help="Bitcoin address or transaction id (64 hexadecimal characters) to look up in WalletExplorer",
    )
    return parser


def _build_provider(name: str, env: Mapping[str, str]) -> Any:
    """Create a real provider by name (imported lazily to keep start-up light)."""
    if name == "mempool.space":
        from .providers.mempool_space import MempoolSpaceProvider

        return MempoolSpaceProvider()
    if name == "blockscout":
        from .providers.blockscout import BlockscoutProvider

        return BlockscoutProvider()
    if name == "etherscan":
        from .providers.etherscan import EtherscanProvider

        return EtherscanProvider(env["ETHERSCAN_API_KEY"])
    if name == "routescan":
        from .providers.routescan import RoutescanProvider

        return RoutescanProvider()
    if name == "blockchain.com":
        from .providers.blockchain_com import BlockchainComProvider

        return BlockchainComProvider(env.get("BLOCKCHAIN_API_KEY"))
    if name == "walletexplorer.com":
        from .providers.walletexplorer import WalletExplorerProvider

        return WalletExplorerProvider()
    if name == "coingecko":
        from .providers.coingecko import CoinGeckoProvider

        return CoinGeckoProvider(env["COINGECKO_API_KEY"])
    raise ValueError(f"Unknown provider: {name!r}")


class _Context:
    def __init__(
        self,
        env: Mapping[str, str],
        providers: Mapping[str, Any] | None,
        out: TextIO,
        err: TextIO,
        today: date | None,
    ) -> None:
        self.env = env
        self.providers = providers or {}
        self.out = out
        self.err = err
        self.today = today
        self.secrets = [env.get(v) for v in _KEY_VARIABLES]

    def say(self, text: str = "") -> None:
        print(mask_secrets(text, self.secrets), file=self.out)

    def warn(self, text: str) -> None:
        print(mask_secrets(text, self.secrets), file=self.err)

    def provider(self, chain: str, requested: str | None = None) -> Any:
        try:
            selection = config.select_provider(chain, self.env, requested)
        except ValueError as exc:
            raise _InputError(str(exc)) from None
        if selection.notice:
            self.warn(f"Notice: {selection.notice}")
        if selection.provider in self.providers:
            return self.providers[selection.provider]
        return _build_provider(selection.provider, self.env)

    def provider_by_name(self, name: str) -> Any:
        """Return the injected provider called `name`, or build the real one."""
        if name in self.providers:
            return self.providers[name]
        return _build_provider(name, self.env)


def _chain_of(address: str) -> tuple[str, str]:
    """Return ``(chain, normalized address)`` or raise an input error."""
    coin = detect_coin(address)
    if coin == UNKNOWN:
        raise InvalidAddressError(address.strip())
    chain = _COIN_TO_CHAIN.get(coin)
    if chain is None:
        raise _InputError(
            f"{coin} addresses are detected but not supported by this command. "
            "Supported chains: Bitcoin, Ethereum."
        )
    return chain, normalize_address(address)


def _cmd_detect(args: argparse.Namespace, ctx: _Context) -> None:
    coin = detect_coin(args.address)
    if coin == UNKNOWN:
        raise InvalidAddressError(args.address.strip())
    ctx.say(f"Detected coin: {coin}")


def _cmd_balance(args: argparse.Namespace, ctx: _Context) -> None:
    chain, address = _chain_of(args.address)
    provider = ctx.provider(chain, args.provider)
    result = provider.get_balance(address)
    unit = _UNIT[chain]
    ctx.say(f"Balance: {result.amount} {unit} (source: {result.source})")
    if args.usd:
        today = ctx.today or datetime.now(timezone.utc).date()
        price_provider = ctx.provider("price")
        value = to_usd(result.amount, chain, today, price_provider.get_price)
        ctx.say(f"Value: {value:,.2f} USD (price of {today.isoformat()})")


def _history_line(tx: Transaction) -> str:
    senders = ",".join(sorted({i.address for i in tx.inputs if i.address})) or "-"
    total = sum((o.value for o in tx.outputs), Decimal(0))
    return (
        f"{format_timestamp(tx.timestamp)}  {tx.txid}  {tx.kind}  "
        f"from {senders}  total out {total}  ({tx.source})"
    )


def _cmd_history(args: argparse.Namespace, ctx: _Context) -> None:
    chain, address = _chain_of(args.address)
    transactions = ctx.provider(chain, args.provider).get_transactions(address, args.limit)
    if not transactions:
        ctx.say("No transactions found.")
        return
    for tx in sorted(transactions, key=lambda t: (t.timestamp, t.txid), reverse=True):
        ctx.say(_history_line(tx))


def _print_graph(graph: FundsGraph, ctx: _Context) -> None:
    unit = _UNIT[graph.chain]
    ctx.say(f"Origin: {graph.origin} ({graph.chain}), hops: {graph.hops}")
    ctx.say(f"Addresses reached: {len(graph.nodes)}")
    for node, distance in graph.nodes.items():
        ctx.say(f"  hop {distance}: {node}")
    ctx.say(f"Transfers: {len(graph.edges)}")
    for e in graph.edges:
        ctx.say(
            f"  {e.source} -> {e.target}  {e.value} {unit}  "
            f"{format_timestamp(e.timestamp)}  {e.txid}  ({e.provider})"
        )


def _cmd_trace(args: argparse.Namespace, ctx: _Context) -> None:
    chain, address = _chain_of(args.address)
    provider = ctx.provider(chain, args.provider)
    _print_graph(trace(address, provider, args.hops, args.limit), ctx)


def _cmd_patterns(args: argparse.Namespace, ctx: _Context) -> None:
    chain, address = _chain_of(args.address)
    transactions = ctx.provider(chain, args.provider).get_transactions(address, args.limit)
    findings = detect_patterns(transactions, victim=address)
    if not findings:
        ctx.say("No patterns found. Results are heuristics, not proof.")
        return
    for f in findings:
        ctx.say(f"{f.pattern}: {', '.join(f.txids)}")
        ctx.say(f"  {f.detail}")


def _transfer_line(tx: Transaction, unit: str) -> str:
    sender = tx.inputs[0].address or "-"
    receiver = tx.outputs[0].address or "-"
    return f"  {sender} -> {receiver}  {tx.outputs[0].value} {unit}"


def _print_transaction(detail: TransactionDetail, ctx: _Context) -> None:
    ctx.say(f"Transaction: {detail.txid}")
    status = {True: "success", False: "failed", None: "unknown (receipt without status)"}[detail.success]
    ctx.say(f"Status: {status}")
    ctx.say(f"Block: {detail.block if detail.block is not None else '-'}")
    ctx.say(f"Date (UTC): {format_timestamp(detail.timestamp)}")
    ctx.say(f"From (signed and paid the gas): {detail.sender or '-'}")
    ctx.say(f"To: {detail.recipient or '- (contract creation)'}")
    ctx.say(f"Value: {detail.value} ETH")
    ctx.say(f"Fee paid: {detail.fee} ETH (gas used {detail.gas_used})")
    ctx.say(f"Method: {detail.method or '-'}")
    ctx.say(f"Internal transactions: {len(detail.internal)}")
    for tx in detail.internal:
        ctx.say(_transfer_line(tx, "ETH"))
    if detail.token_transfers is None:
        ctx.say(
            f"Token transfers: not reported by {detail.source} for a single "
            "transaction"
        )
    else:
        ctx.say(f"Token transfers: {len(detail.token_transfers)}")
        for tx in detail.token_transfers:
            ctx.say(_transfer_line(tx, "units"))
    ctx.say(f"Source: {detail.source}")


def _cmd_tx(args: argparse.Namespace, ctx: _Context) -> None:
    text = args.hash.strip()
    if not is_ethereum_tx_hash(text):
        raise _InputError(
            f"Not an Ethereum transaction hash: {text!r} (expected 0x followed by 64 hexadecimal characters)"
        )
    provider = ctx.provider("ethereum", args.provider)
    if not hasattr(provider, "get_transaction"):
        raise _InputError(f"Provider '{provider.name}' cannot show a single transaction.")
    _print_transaction(provider.get_transaction(text.lower()), ctx)


def _cmd_cluster(args: argparse.Namespace, ctx: _Context) -> None:
    text = args.argument.strip()
    kind = classify_cluster_input(text)
    if kind == INPUT_UNKNOWN:
        coin = detect_coin(text)
        if coin != UNKNOWN:
            raise _InputError(
                f"{coin} addresses are detected but WalletExplorer covers Bitcoin only."
            )
        raise _InputError(
            f"Not a Bitcoin address or transaction id: {text!r}"
        )
    provider = ctx.provider_by_name("walletexplorer.com")
    if kind == INPUT_ADDRESS:
        result = provider.lookup_address(normalize_address(text))
    else:
        result = provider.lookup_tx(text)
    for line in format_cluster(result):
        ctx.say(line)


def _cmd_report(args: argparse.Namespace, ctx: _Context) -> None:
    chain, address = _chain_of(args.address)
    provider = ctx.provider(chain, args.provider)
    graph = trace(address, provider, args.hops, DEFAULT_LIMIT)
    evidences: list[Evidence] = []
    seen: set[str] = set()
    for e in graph.edges:
        if e.txid in seen:
            continue
        seen.add(e.txid)
        evidences.append(
            Evidence(
                txid=e.txid,
                timestamp=e.timestamp,
                source=e.provider,
                note=f"{e.source} -> {e.target}: {e.value} {_UNIT[chain]}",
            )
        )
    findings = detect_patterns(
        provider.get_transactions(graph.origin, DEFAULT_LIMIT), victim=graph.origin
    )
    text = render_report(
        evidences, findings, address=graph.origin, coin=chain, hops=args.hops
    )
    text = mask_secrets(text, ctx.secrets)
    if args.out:
        try:
            with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
        except OSError as exc:
            raise _OutputError(f"Cannot write report to '{args.out}': {exc.strerror or exc}") from None
        ctx.say(f"Report written to {args.out}")
    else:
        ctx.out.write(text)


class _OutputError(Exception):
    """Failure writing an output file, reported with exit code 1."""


_COMMANDS = {
    "detect": _cmd_detect,
    "balance": _cmd_balance,
    "history": _cmd_history,
    "trace": _cmd_trace,
    "patterns": _cmd_patterns,
    "report": _cmd_report,
    "cluster": _cmd_cluster,
    "tx": _cmd_tx,
}


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    providers: Mapping[str, Any] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    today: date | None = None,
) -> int:
    """Run the CLI and return the exit code.

    Args:
        argv: Arguments without the program name (default: ``sys.argv[1:]``).
        env: Configuration variables (default: ``.env`` merged with the process
            environment).
        providers: Ready-made providers by name, used instead of the real ones.
            Intended for tests.
        stdout: Output stream (default: ``sys.stdout``).
        stderr: Error stream (default: ``sys.stderr``).
        today: Date used for the ``--usd`` price (default: today, UTC).
    """
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return EXIT_OK if exc.code in (0, None) else EXIT_INPUT

    values = config.load_env() if env is None else env
    ctx = _Context(values, providers, out, err, today)
    try:
        _COMMANDS[args.command](args, ctx)
    except (InvalidAddressError, _InputError, ValueError) as exc:
        ctx.warn(f"Error: {exc}")
        return EXIT_INPUT
    except (ProviderError, MissingKeyError, _OutputError) as exc:
        ctx.warn(f"Error: {exc}")
        return EXIT_PROVIDER
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
