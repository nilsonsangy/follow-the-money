"""Markdown trace report: rendering and lossless parsing of the evidence table.

Layout::

    # Trace report: <address>
    Generated: <ISO 8601 UTC> | Coin: <coin> | Hops: <n>

    ## Evidence
    | # | Transaction hash | Date (UTC) | Source | Note |
    |---|---|---|---|---|
    | 1 | <txid> | 2024-01-01T00:00:00Z | mempool.space | ... |

    ## Findings
    - <pattern>: <txid>, <txid>

Rendering is deterministic: the same inputs always produce the same text.
Table cells escape ``\\``, ``|`` and line breaks so that any hash, source or
note survives ``parse_report(render_report(evidences))`` unchanged.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime, timezone

from .models import Evidence, Finding

_EVIDENCE_HEADING = "## Evidence"
_TABLE_HEADER = "| # | Transaction hash | Date (UTC) | Source | Note |"
_TABLE_SEPARATOR = "|---|---|---|---|---|"


def format_timestamp(value: datetime) -> str:
    """Serialize a datetime as ISO 8601 UTC with a ``Z`` suffix, keeping microseconds.

    Naive datetimes are taken as UTC.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    if value.microsecond:
        return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_timestamp(text: str) -> datetime:
    """Inverse of :func:`format_timestamp`; returns a timezone-aware UTC datetime."""
    text = text.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _escape_cell(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )


def _split_row(line: str) -> list[str]:
    """Split a table row on unescaped pipes and unescape each cell."""
    cells: list[str] = []
    current: list[str] = []
    i = 0
    while i < len(line):
        char = line[i]
        if char == "\\" and i + 1 < len(line):
            nxt = line[i + 1]
            current.append({"n": "\n", "r": "\r"}.get(nxt, nxt))
            i += 2
            continue
        if char == "|":
            cells.append("".join(current))
            current = []
        else:
            current.append(char)
        i += 1
    cells.append("".join(current))
    # Drop the empty fragments before the first and after the last pipe.
    return cells[1:-1]


def _strip_padding(cell: str) -> str:
    """Remove the single padding space added on each side by the renderer."""
    if cell.startswith(" "):
        cell = cell[1:]
    if cell.endswith(" "):
        cell = cell[:-1]
    return cell


def render_report(
    evidences: Sequence[Evidence],
    findings: Iterable[Finding] = (),
    *,
    address: str = "",
    coin: str = "",
    hops: int = 0,
    generated: datetime | None = None,
) -> str:
    """Render a Markdown report with an evidence table and a findings list.

    Every evidence row carries the transaction hash, the UTC date, the source
    and a note. ``generated`` is optional so that output stays reproducible.
    """
    header_parts = []
    if generated is not None:
        header_parts.append(f"Generated: {format_timestamp(generated)}")
    header_parts.append(f"Coin: {coin}")
    header_parts.append(f"Hops: {hops}")

    lines = [
        f"# Trace report: {address}",
        " | ".join(header_parts),
        "",
        _EVIDENCE_HEADING,
        _TABLE_HEADER,
        _TABLE_SEPARATOR,
    ]
    for index, ev in enumerate(evidences, start=1):
        cells = [
            str(index),
            _escape_cell(ev.txid),
            format_timestamp(ev.timestamp),
            _escape_cell(ev.source),
            _escape_cell(ev.note),
        ]
        lines.append("| " + " | ".join(cells) + " |")

    lines += ["", "## Findings"]
    for finding in findings:
        lines.append(f"- {finding.pattern}: {', '.join(finding.txids)}")
    return "\n".join(lines) + "\n"


def parse_report(text: str) -> list[Evidence]:
    """Read the evidence table of a report back into ``Evidence`` objects, in order."""
    lines = text.split("\n")
    try:
        start = lines.index(_EVIDENCE_HEADING)
    except ValueError:
        return []

    evidences: list[Evidence] = []
    seen_header = False
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        if not line.startswith("|"):
            if seen_header and not line.strip():
                break
            continue
        if line == _TABLE_HEADER:
            seen_header = True
            continue
        if line == _TABLE_SEPARATOR:
            continue
        cells = [_strip_padding(c) for c in _split_row(line)]
        if len(cells) != 5:
            raise ValueError(f"Malformed evidence row: {line!r}")
        _, txid, date, source, note = cells
        evidences.append(
            Evidence(txid=txid, timestamp=parse_timestamp(date), source=source, note=note)
        )
    return evidences
