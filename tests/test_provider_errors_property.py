"""Property-based and example tests for provider errors.

Feature: crypto-tracing, Property 13: a provider failure raises an error whose
message names the source and the reason, is written in English and never
contains an API key value.

**Validates: Requirements 9.12, 15.11**
"""
from __future__ import annotations

import httpx
import pytest
from hypothesis import given, strategies as st

from follow_the_money.errors import ProviderError, RateLimitError
from follow_the_money.providers import blockchair, etherscan, mempool_space
from follow_the_money.providers._http import HttpClient

# Keys carry a fixed prefix so they cannot collide with words in the message.
keys = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=12, max_size=40).map(
    lambda s: "k3y" + s
)
provider_names = st.sampled_from([etherscan.NAME, blockchair.NAME, mempool_space.NAME])
error_statuses = st.sampled_from([400, 401, 403, 404, 429, 500, 502, 503])


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _assert_message(exc: ProviderError, provider: str, key: str) -> None:
    message = str(exc)
    assert exc.provider == provider
    assert exc.reason
    assert provider in message
    assert exc.reason in message
    assert key not in message
    assert key not in exc.reason
    assert message.isascii()


def _failing_client(mode: str, status: int) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if mode == "network":
            raise httpx.ConnectError(f"cannot connect to {request.url}", request=request)
        if mode == "json":
            return httpx.Response(200, content=b"not json")
        return httpx.Response(status, json={})

    return _client(handler)


@given(provider_names, keys, st.sampled_from(["status", "json", "network"]), error_statuses)
def test_failure_names_source_and_reason_without_key(provider, key, mode, status):
    http = HttpClient(
        provider, "https://api.example.test", secrets=(key,), client=_failing_client(mode, status)
    )
    with pytest.raises(ProviderError) as info:
        http.get_json("/path", {"apikey": key})
    _assert_message(info.value, provider, key)
    if mode == "status":
        assert isinstance(info.value, RateLimitError) == (status == 429)


def test_rate_limit_is_reported_without_retry_or_key():
    key = "k3yexamplekey123456"
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(429, json={"message": "Too Many Requests"})

    with pytest.raises(RateLimitError) as info:
        etherscan.EtherscanProvider(key, client=_client(handler)).get_balance("0x" + "a" * 40)
    assert len(calls) == 1
    assert info.value.provider == etherscan.NAME
    assert key not in str(info.value)

    open_client = _client(lambda request: httpx.Response(429))
    with pytest.raises(RateLimitError):
        mempool_space.MempoolSpaceProvider(client=open_client).get_transactions("1" * 30, 10)

    envelope = {"status": "0", "message": "NOTOK", "result": "Max rate limit reached"}
    with pytest.raises(RateLimitError):
        etherscan.unwrap_result(envelope)
    with pytest.raises(ProviderError) as other:
        etherscan.unwrap_result({"status": "0", "message": "x", "result": "Invalid API Key"})
    assert etherscan.NAME in str(other.value)
