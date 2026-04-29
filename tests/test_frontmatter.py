"""Frontmatter parse/dump round-trip and edge cases."""

from __future__ import annotations

import pytest

from pace import frontmatter


def test_parse_returns_empty_when_no_frontmatter() -> None:
    body = "Just a paragraph.\n"
    fm, rest = frontmatter.parse(body)
    assert fm == {}
    assert rest == body


def test_parse_extracts_yaml_mapping() -> None:
    text = "---\ntitle: Test\ntags: [a, b]\n---\nbody here\n"
    fm, body = frontmatter.parse(text)
    assert fm == {"title": "Test", "tags": ["a", "b"]}
    assert body == "body here\n"


def test_parse_rejects_non_mapping_frontmatter() -> None:
    with pytest.raises(ValueError):
        frontmatter.parse("---\n- a\n- b\n---\nbody\n")


def test_dump_then_parse_round_trip_preserves_data() -> None:
    fm_in = {"title": "Round Trip", "tags": ["x", "y"], "kind": "long_term"}
    body_in = "## 2026-04-27\n\nFact.\n"
    text = frontmatter.dump(fm_in, body_in)
    fm_out, body_out = frontmatter.parse(text)
    assert fm_out == fm_in
    assert body_out == body_in


def test_dump_preserves_key_order() -> None:
    fm = {"title": "A", "kind": "working", "tags": []}
    text = frontmatter.dump(fm, "")
    # Keys should appear in the order they were inserted.
    title_idx = text.index("title:")
    kind_idx = text.index("kind:")
    tags_idx = text.index("tags:")
    assert title_idx < kind_idx < tags_idx
