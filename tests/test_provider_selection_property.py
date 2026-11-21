"""Property-based tests for provider selection.

Feature: crypto-tracing, Property 11: provider selection.
**Validates: Requirements 15.2, 15.3, 15.4, 15.5**
"""
from __future__ import annotations

import pytest
from hypothesis import given, strategies as st

from follow_the_money.config import select_provider
from follow_the_money.errors import MissingKeyError

OPEN = {"bitcoin": "mempool.space", "ethereum": "blockscout"}
KEYED = {
    "bitcoin": ("blockchair", "BLOCKCHAIR_API_KEY"),
    "ethereum": ("etherscan", "ETHERSCAN_API_KEY"),
    "price": ("coingecko", "COINGECKO_API_KEY"),
}
ALL_VARS = [v for _, v in KEYED.values()]

key_values = st.text(
    alphabet=st.characters(blacklist_categories=("Cs", "Cc")), min_size=1, max_size=30
)
# Any subset of the configured keys, plus unrelated variables.
envs = st.fixed_dictionaries(
    {},
    optional={v: key_values for v in ALL_VARS},
).flatmap(
    lambda base: st.dictionaries(
        st.text(alphabet="ABCXYZ_", min_size=1, max_size=8).filter(
            lambda k: k not in ALL_VARS
        ),
        key_values,
        max_size=3,
    ).map(lambda extra: {**extra, **base})
)
chains = st.sampled_from(["bitcoin", "ethereum", "price"])
request_keyed = st.booleans()


@given(chain=chains, env=envs, ask_keyed=request_keyed)
def test_provider_selection(chain, env, ask_keyed):
    keyed_name, variable = KEYED[chain]
    open_name = OPEN.get(chain)
    requested = keyed_name if ask_keyed else None
    has_key = variable in env

    if open_name is None:
        # No open equivalent (historical price): key is mandatory.
        if has_key:
            sel = select_provider(chain, env, requested)
            assert sel.provider == keyed_name
            assert sel.requires_key == variable
            assert sel.notice is None
        else:
            with pytest.raises(MissingKeyError) as exc:
                select_provider(chain, env, requested)
            assert exc.value.variable == variable
            assert variable in str(exc.value)
            assert "https://" in exc.value.how_to_get
            assert exc.value.how_to_get in str(exc.value)
        return

    sel = select_provider(chain, env, requested)
    if not ask_keyed:
        # Open provider is the default and needs no key.
        assert sel.provider == open_name
        assert sel.requires_key is None
        assert sel.notice is None
    elif has_key:
        assert sel.provider == keyed_name
        assert sel.requires_key == variable
        assert sel.notice is None
    else:
        # Missing key with an open equivalent: fall back and name it.
        assert sel.provider == open_name
        assert sel.requires_key is None
        assert sel.notice is not None
        assert open_name in sel.notice
        assert variable in sel.notice
