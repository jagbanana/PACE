"""Reindex picks up direct edits and removes deleted files."""

from __future__ import annotations

from pathlib import Path

from pace import frontmatter
from pace import vault as vault_ops
from pace.capture import capture
from pace.index import Index
from pace.paths import LONG_TERM_DIR


def test_reindex_picks_up_direct_edits(vault: Path, index: Index) -> None:
    capture(vault, kind="long_term", topic="People", content="Initial fact.", index=index)

    # Edit the file directly (simulating Obsidian use).
    target = vault / LONG_TERM_DIR / "people.md"
    fm, body = frontmatter.parse(target.read_text(encoding="utf-8"))
    body += "\n\n## 2026-04-27 10:00\n\nDirectly-edited new fact about widgets.\n"
    target.write_text(frontmatter.dump(fm, body), encoding="utf-8")

    # Pre-reindex: search should miss the new content.
    assert index.search("widgets") == []

    result = vault_ops.reindex(vault, index)
    assert result.indexed >= 1
    assert result.removed == 0

    # Post-reindex: search finds it.
    hits = index.search("widgets")
    assert len(hits) == 1


def test_reindex_removes_deleted_files(vault: Path, index: Index) -> None:
    capture(vault, kind="long_term", topic="Vendors", content="Acme is preferred.", index=index)
    target = vault / LONG_TERM_DIR / "vendors.md"
    assert index.get_by_path("memories/long_term/vendors.md") is not None

    target.unlink()
    result = vault_ops.reindex(vault, index)
    assert result.removed == 1
    assert index.get_by_path("memories/long_term/vendors.md") is None


def test_reindex_is_idempotent(vault: Path, index: Index) -> None:
    capture(vault, kind="working", content="Stable fact.", index=index)
    capture(vault, kind="long_term", topic="People", content="Alex is COO.", index=index)

    first = vault_ops.reindex(vault, index)
    second = vault_ops.reindex(vault, index)

    # Same set of files indexed both times; nothing removed on the second pass.
    assert first.indexed == second.indexed
    assert second.removed == 0
