"""Property-based tests for secret masking.

Feature: crypto-tracing, Property 12: keys never appear in the output.

**Validates: Requirements 15.9, 15.10**
"""
from __future__ import annotations

from hypothesis import given, strategies as st

from follow_the_money.masking import MASK, mask_secrets

# Keys are non-empty and never contain the mask character.
secret_values = st.text(
    alphabet=st.characters(
        blacklist_characters="*", blacklist_categories=("Cs", "Cc")
    ),
    min_size=1,
    max_size=40,
)
fragments = st.text(
    alphabet=st.characters(
        blacklist_characters="*", blacklist_categories=("Cs",)
    ),
    max_size=30,
)


@st.composite
def text_with_secrets(draw):
    secrets = draw(st.lists(secret_values, min_size=1, max_size=4))
    parts = [draw(fragments)]
    for _ in range(draw(st.integers(min_value=1, max_value=5))):
        parts.append(draw(st.sampled_from(secrets)))
        parts.append(draw(fragments))
    return "".join(parts), secrets


@given(text_with_secrets(), fragments)
def test_secrets_never_appear_and_empty_secrets_change_nothing(data, plain):
    text, secrets = data
    masked = mask_secrets(text, secrets)
    assert MASK in masked
    for secret in secrets:
        assert secret not in masked
    assert mask_secrets(plain, ["", None]) == plain
