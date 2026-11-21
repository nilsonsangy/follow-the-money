"""Masking of secret values (API keys) in any text written by the tool."""

from __future__ import annotations

from collections.abc import Iterable

MASK = "***"


def mask_secrets(text: str, secrets: Iterable[str | None]) -> str:
    """Replace every occurrence of each non-empty secret value in ``text`` with ``***``.

    Empty and ``None`` values are ignored. Longer secrets are replaced first so
    that a secret containing another one is never left partially exposed.
    """
    values = sorted({s for s in secrets if s}, key=len, reverse=True)
    for value in values:
        text = text.replace(value, MASK)
    return text
