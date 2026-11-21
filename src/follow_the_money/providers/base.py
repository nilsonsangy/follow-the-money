"""Provider interface shared by every data source."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..models import Balance, Transaction


@runtime_checkable
class Provider(Protocol):
    """A blockchain data source.

    ``requires_key`` holds the environment variable that must be set to use the
    provider, or ``None`` when the provider is open (no key needed).
    """

    name: str
    chain: str  # "bitcoin" | "ethereum" | "price"
    requires_key: str | None

    def get_balance(self, address: str) -> Balance: ...

    def get_transactions(self, address: str, limit: int) -> list[Transaction]: ...
