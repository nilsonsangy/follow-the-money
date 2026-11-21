"""Property: parse_report(render_report(evidences)) returns the same evidences."""

from datetime import datetime, timezone

from hypothesis import given, strategies as st

from follow_the_money.models import Evidence, Finding
from follow_the_money.report import parse_report, render_report

_text = st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=40)
_evidence = st.builds(
    Evidence,
    txid=st.text(alphabet="0123456789abcdefx", min_size=1, max_size=64),
    timestamp=st.datetimes(
        min_value=datetime(2009, 1, 1), max_value=datetime(2100, 1, 1), timezones=st.just(timezone.utc)
    ),
    source=_text,
    note=_text,
)


@given(st.lists(_evidence, max_size=10))
def test_report_roundtrip(evidences):
    """Property 9: report round trip.

    List equality checks hashes (txid), dates (timestamp), sources and order.

    **Validates: Requirements 9.8, 9.17**
    """
    text = render_report(
        evidences, [Finding("peel_chain", ("a", "b"), "d")], address="addr", coin="bitcoin", hops=3
    )
    assert parse_report(text) == evidences
