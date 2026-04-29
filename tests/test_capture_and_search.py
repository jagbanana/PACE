"""Round-trip capture → search and frontmatter integrity on append."""

from __future__ import annotations

from pathlib import Path

from pace import frontmatter
from pace.capture import capture
from pace.index import Index
from pace.paths import LONG_TERM_DIR, WORKING_MEMORY


def test_working_capture_then_search_finds_entry(vault: Path, index: Index) -> None:
    capture(
        vault,
        kind="working",
        content="The user's primary KPI for 2026 is gross margin.",
        tags=["high-signal", "business"],
        index=index,
    )
    hits = index.search("gross margin")
    assert len(hits) == 1
    assert hits[0].path == WORKING_MEMORY
    assert hits[0].kind == "working"
    assert "gross" in hits[0].snippet.lower()


def test_long_term_capture_creates_topic_file(vault: Path, index: Index) -> None:
    target = capture(
        vault,
        kind="long_term",
        topic="People",
        content="Alex is the user's COO. Alex prefers brevity.",
        tags=["person"],
        index=index,
    )
    assert target == vault / LONG_TERM_DIR / "people.md"
    assert target.is_file()

    hits = index.search("COO")
    assert len(hits) == 1
    assert hits[0].kind == "long_term"
    assert hits[0].title == "People"


def test_capture_preserves_existing_frontmatter(vault: Path, index: Index) -> None:
    # Seed an existing long_term file with a custom frontmatter field.
    seed_path = vault / LONG_TERM_DIR / "people.md"
    seed_fm = {
        "title": "People",
        "kind": "long_term",
        "date_created": "2026-01-01T09:00:00",
        "date_modified": "2026-01-01T09:00:00",
        "tags": ["person"],
        "custom_field": "preserved",
    }
    seed_path.parent.mkdir(parents=True, exist_ok=True)
    seed_path.write_text(
        frontmatter.dump(seed_fm, "## 2026-01-01 09:00\n\nSeed entry.\n"),
        encoding="utf-8",
    )

    capture(
        vault,
        kind="long_term",
        topic="People",
        content="A new fact about people.",
        tags=["person"],
        index=index,
    )

    fm, body = frontmatter.parse(seed_path.read_text(encoding="utf-8"))
    assert fm["custom_field"] == "preserved"
    assert fm["date_created"] == "2026-01-01T09:00:00"  # unchanged
    assert fm["date_modified"] != "2026-01-01T09:00:00"  # bumped
    assert "Seed entry." in body
    assert "A new fact about people." in body


def test_multiple_captures_share_same_file(vault: Path, index: Index) -> None:
    capture(vault, kind="working", content="Fact one.", tags=["fact"], index=index)
    capture(vault, kind="working", content="Fact two.", tags=["fact"], index=index)

    hits = index.search("fact")
    # Both facts live in working_memory.md → exactly one file matches.
    assert len(hits) == 1
    body = (vault / WORKING_MEMORY).read_text(encoding="utf-8")
    assert "Fact one." in body
    assert "Fact two." in body


def test_tags_normalize_with_hash_prefix(vault: Path, index: Index) -> None:
    capture(
        vault,
        kind="working",
        content="Entry with bare tags.",
        tags=["business", "#decision"],
        index=index,
    )
    body = (vault / WORKING_MEMORY).read_text(encoding="utf-8")
    assert "#business" in body
    assert "#decision" in body
