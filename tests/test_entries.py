"""Markdown append-log entry parsing."""

from __future__ import annotations

from pace.entries import Entry, append, join, remove, split

SAMPLE = """\
## 2026-04-20 09:00 — #person #user

Alex is the user's COO; prefers brevity.

## 2026-04-21 10:30

Untagged note about the weekly cadence.

## 2026-04-22 14:45 — #high-signal #decision

User decided to ship internal-first then GitHub.
"""


def test_split_extracts_three_entries() -> None:
    entries = split(SAMPLE)
    assert len(entries) == 3
    assert entries[0].tags == ["#person", "#user"]
    assert "Alex" in entries[0].body
    assert entries[1].tags == []
    assert entries[2].tags == ["#high-signal", "#decision"]


def test_split_returns_empty_for_no_headings() -> None:
    assert split("") == []
    assert split("Just prose with no headings.\n") == []


def test_join_round_trips_split() -> None:
    entries = split(SAMPLE)
    rejoined = join(entries)
    # Round-trip should preserve every entry's heading + content.
    for entry in entries:
        assert entry.heading in rejoined
        assert entry.body in rejoined


def test_remove_drops_only_matching_entry() -> None:
    body, removed = remove(SAMPLE, "## 2026-04-21 10:30")
    assert removed is not None
    assert "Untagged note" not in body
    assert "Alex" in body  # the other two entries survive
    assert "shipped internal" not in body  # exact text not present anyway
    assert "User decided to ship" in body


def test_remove_returns_none_when_no_match() -> None:
    body, removed = remove(SAMPLE, "## 2030-01-01 00:00")
    assert removed is None
    assert body == SAMPLE


def test_append_adds_entry_with_blank_line_separator() -> None:
    entries = split(SAMPLE)
    new_entry = Entry(
        heading="## 2026-04-23 08:15 — #fact",
        timestamp=entries[0].timestamp,  # value not material for this test
        tags=["#fact"],
        body="A new fact.",
    )
    new_body = append(SAMPLE, new_entry)
    assert "A new fact." in new_body
    assert new_body.count("## 20") == 4
