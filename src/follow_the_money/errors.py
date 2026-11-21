"""Exceptions raised by providers, configuration and address validation."""

from __future__ import annotations


class ProviderError(Exception):
    """A provider request failed or returned an unexpected response."""

    def __init__(self, provider: str, reason: str) -> None:
        self.provider = provider
        self.reason = reason
        super().__init__(f"Provider '{provider}' failed: {reason}")


class MissingKeyError(Exception):
    """A required API key is not configured and no open provider is available."""

    def __init__(self, variable: str, how_to_get: str) -> None:
        self.variable = variable
        self.how_to_get = how_to_get
        super().__init__(
            f"Missing API key: set {variable} in the .env file. {how_to_get}"
        )


class RateLimitError(ProviderError):
    """A provider rejected the request because its free limit was reached (HTTP 429)."""

    def __init__(self, provider: str, limit: str = "free tier limit") -> None:
        self.limit = limit
        super().__init__(provider, f"rate limit reached ({limit}); try again later")


class InvalidAddressError(ValueError):
    """The given text does not match any known Bitcoin or Ethereum address format."""

    def __init__(self, address: str) -> None:
        self.address = address
        super().__init__(
            f"Invalid address: '{address}' is not a recognized Bitcoin or Ethereum address"
        )
