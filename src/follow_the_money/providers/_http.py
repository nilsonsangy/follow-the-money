"""Network I/O shared by providers: one ``httpx`` client with masking and 429 handling."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import httpx

from ..errors import ProviderError, RateLimitError
from ..masking import mask_secrets

DEFAULT_TIMEOUT = 20.0


class HttpClient:
    """Thin JSON client for one provider.

    Every URL, header value and error message that leaves this class is passed
    through :func:`mask_secrets`. HTTP 429 raises :class:`RateLimitError`
    immediately; there is no retry loop.
    """

    def __init__(
        self,
        provider: str,
        base_url: str,
        *,
        secrets: Iterable[str | None] = (),
        headers: Mapping[str, str] | None = None,
        client: httpx.Client | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.provider = provider
        self.base_url = base_url.rstrip("/")
        self._secrets = tuple(s for s in secrets if s)
        self._headers = dict(headers or {})
        self._client = client or httpx.Client(timeout=timeout)

    def _mask(self, text: str) -> str:
        return mask_secrets(text, self._secrets)

    def get_json(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            response = self._client.get(url, params=params, headers=self._headers)
        except httpx.HTTPError as exc:
            raise ProviderError(
                self.provider, self._mask(f"network error: {exc}")
            ) from None
        if response.status_code == 429:
            raise RateLimitError(self.provider)
        if response.status_code >= 400:
            raise ProviderError(
                self.provider,
                self._mask(f"HTTP {response.status_code} for {response.request.url}"),
            )
        try:
            return response.json()
        except ValueError:
            raise ProviderError(
                self.provider,
                self._mask(f"unexpected response: invalid JSON from {response.request.url}"),
            ) from None
