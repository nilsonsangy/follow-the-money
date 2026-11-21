"""Configuration: a single ``.env`` file and provider selection."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .errors import MissingKeyError

ENV_FILE = ".env"

# chain -> (open default, {keyed provider: (variable, how to get the key)})
_OPEN_DEFAULTS: dict[str, str | None] = {
    "bitcoin": "mempool.space",
    "ethereum": "blockscout",
    "price": None,  # no open equivalent
}

_KEYED: dict[str, dict[str, tuple[str, str]]] = {
    "bitcoin": {
        "blockchair": (
            "BLOCKCHAIR_API_KEY",
            "Get a free key at https://blockchair.com/api/plans.",
        ),
    },
    "ethereum": {
        "etherscan": (
            "ETHERSCAN_API_KEY",
            "Get a free key at https://etherscan.io/apis.",
        ),
    },
    "price": {
        "coingecko": (
            "COINGECKO_API_KEY",
            "Get a free demo key at https://www.coingecko.com/en/api.",
        ),
    },
}


@dataclass(frozen=True)
class Selection:
    """Result of provider selection.

    ``notice`` is a message for the user when the open provider was used
    because a requested key is missing, otherwise ``None``.
    """

    provider: str
    requires_key: str | None
    notice: str | None = None


def parse_env(text: str) -> dict[str, str]:
    """Parse ``KEY=value`` lines. Blank lines and ``#`` comments are ignored."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def load_env(
    path: str | Path | None = None, environ: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Read the only ``.env`` file (current directory by default).

    Variables already present in ``environ`` (default: the process
    environment) take precedence over the file. Empty values count as unset.
    """
    env_path = Path(path) if path is not None else Path.cwd() / ENV_FILE
    values: dict[str, str] = {}
    if env_path.is_file():
        values.update(parse_env(env_path.read_text(encoding="utf-8")))
    values.update(os.environ if environ is None else environ)
    return {k: v for k, v in values.items() if v != ""}


def select_provider(
    chain: str, env: Mapping[str, str], requested: str | None = None
) -> Selection:
    """Choose a provider for ``chain`` from the configured variables in ``env``.

    Pure: no I/O. Open providers (mempool.space for Bitcoin, Blockscout for
    Ethereum) are the default. A keyed provider is used only when requested and
    its key is set. If the key is missing, the open provider is used with a
    notice. When no open equivalent exists, ``MissingKeyError`` is raised.
    """
    if chain not in _OPEN_DEFAULTS:
        raise ValueError(f"Unknown chain: {chain!r}")
    open_name = _OPEN_DEFAULTS[chain]
    keyed = _KEYED[chain]

    if requested is None:
        if open_name is not None:
            return Selection(open_name, None)
        requested = next(iter(keyed))
    name = requested.lower()

    if name == open_name:
        return Selection(open_name, None)
    if name not in keyed:
        raise ValueError(f"Unknown provider for {chain}: {requested!r}")

    variable, how_to_get = keyed[name]
    if env.get(variable):
        return Selection(name, variable)
    if open_name is None:
        raise MissingKeyError(variable, how_to_get)
    return Selection(
        open_name,
        None,
        f"{variable} is not set; using open provider '{open_name}' instead of '{name}'. "
        f"{how_to_get}",
    )
