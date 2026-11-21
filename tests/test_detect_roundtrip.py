"""Property 4: coin detection round trip.

**Validates: Requirements 9.3, 9.15**

For any well-formed Bitcoin or Ethereum address, in any case combination and
with surrounding whitespace, ``detect_coin`` returns the generator's coin for
both the original address and the normalized address.
"""

from __future__ import annotations

from hypothesis import given, strategies as st

from follow_the_money.detect import detect_coin, normalize_address

BASE58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
BECH32 = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
HEX = "0123456789abcdef"

whitespace = st.text(alphabet=" \t\r\n", max_size=4)


@st.composite
def bitcoin_addresses(draw: st.DrawFn) -> str:
    kind = draw(st.sampled_from(["p2pkh", "p2sh", "bech32"]))
    if kind == "bech32":
        body = draw(st.text(alphabet=BECH32, min_size=25, max_size=39))
        address = "bc1" + body
        return address.upper() if draw(st.booleans()) else address
    prefix = "1" if kind == "p2pkh" else "3"
    return prefix + draw(st.text(alphabet=BASE58, min_size=25, max_size=33))


@st.composite
def ethereum_addresses(draw: st.DrawFn) -> str:
    digits = draw(st.text(alphabet=HEX, min_size=40, max_size=40))
    flips = draw(st.lists(st.booleans(), min_size=40, max_size=40))
    mixed = "".join(c.upper() if f else c for c, f in zip(digits, flips))
    return draw(st.sampled_from(["0x", "0X"])) + mixed


addresses = st.one_of(
    bitcoin_addresses().map(lambda a: ("Bitcoin", a)),
    ethereum_addresses().map(lambda a: ("Ethereum", a)),
)


@given(addresses, whitespace, whitespace)
def test_detection_round_trip(case: tuple[str, str], left: str, right: str) -> None:
    coin, address = case
    padded = left + address + right

    assert detect_coin(padded) == coin
    assert detect_coin(normalize_address(padded)) == coin
    assert detect_coin(padded) == detect_coin(normalize_address(padded))
