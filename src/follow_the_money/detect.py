"""Cryptocurrency detection from wallet address format.

Pure functions with no network access. Detection is based on address format
only, so a match indicates the likely coin, not that the address exists.
"""

from __future__ import annotations

import re

UNKNOWN = "Unknown"

# Regular expressions for common cryptocurrency address formats.
ADDRESS_PATTERNS: dict[str, re.Pattern[str]] = {
    # Starts with 1, 3 or bc1 and has 26-42 characters.
    "Bitcoin": re.compile(r"^(1|3|bc1)[a-zA-HJ-NP-Z0-9]{25,39}$"),
    # Starts with 0x and has 42 characters.
    "Ethereum": re.compile(r"^(0x)[0-9a-fA-F]{40}$"),
    # Starts with L, M or ltc1 and has 26-42 characters.
    "Litecoin": re.compile(r"^(L|M|ltc1)[a-zA-HJ-NP-Z0-9]{25,39}$"),
    # Starts with 4 or 8 and has 95 characters.
    "Monero": re.compile(r"^(4|8)[0-9AB][1-9A-HJ-NP-Za-km-z]{93}$"),
}

_BARE_ETHEREUM = re.compile(r"^[0-9a-fA-F]{40}$")
_ETHEREUM_PREFIX = re.compile(r"^0[xX](?=[0-9a-fA-F]{40}$)")
_BECH32_PREFIXES = ("bc1", "ltc1")


def normalize_address(address: str) -> str:
    """Return the canonical form of a wallet address.

    - Surrounding whitespace is removed.
    - Ethereum addresses are lowercased and carry the ``0x`` prefix.
    - Bech32 addresses (``bc1``, ``ltc1``) are lowercased.
    - Base58 addresses keep their original case, which is significant.
    - Any other text is returned stripped and otherwise unchanged.
    """
    text = address.strip()

    if _ETHEREUM_PREFIX.match(text):
        return "0x" + text[2:].lower()
    if _BARE_ETHEREUM.match(text):
        return "0x" + text.lower()

    if text.lower().startswith(_BECH32_PREFIXES):
        return text.lower()

    return text


INPUT_ADDRESS = "address"
INPUT_TXID = "txid"
INPUT_UNKNOWN = "unknown"

# A transaction id: exactly 64 hexadecimal characters, either case.
_TXID_PATTERN = re.compile(r"[0-9a-fA-F]{64}")


def classify_cluster_input(text: str) -> str:
    """Classify the argument of a cluster lookup.

    Args:
        text: The address or transaction id typed by the user.

    Returns:
        ``txid`` for exactly 64 hexadecimal characters (either case),
        ``address`` for a Bitcoin address format, otherwise ``unknown``.
        Addresses of other coins are ``unknown`` here; use ``detect_coin``
        to tell them apart from unrecognized text.
    """
    stripped = text.strip()
    if _TXID_PATTERN.fullmatch(stripped):
        return INPUT_TXID
    if ADDRESS_PATTERNS["Bitcoin"].match(normalize_address(stripped)):
        return INPUT_ADDRESS
    return INPUT_UNKNOWN


def detect_coin(address: str) -> str:
    """Detect the cryptocurrency of a wallet address from its format.

    Args:
        address: The wallet address to check.

    Returns:
        ``Bitcoin``, ``Ethereum``, ``Litecoin``, ``Monero``, or ``Unknown``
        when the text matches no known format.
    """
    normalized = normalize_address(address)
    for coin, pattern in ADDRESS_PATTERNS.items():
        if pattern.match(normalized):
            return coin
    return UNKNOWN
