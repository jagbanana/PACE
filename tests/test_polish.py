"""Polish batch: ref-count window, path classifiers, batched wikilink refs."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from pace import paths
from pace.capture import capture
from pace.index import Index

# ---- #7 reference_count window (local-clock cutoff) -------------------


def test_reference_count_respects_local_window(vault: Path, index: Index) -> None:
    capture(vault, kind="long_term", topic="x", content="hi", index=index)
    tid = index.get_id("memories/long_term/x.md")
    assert tid is not None

    old = (datetime.now() - timedelta(days=100)).isoformat()
    recent = (datetime.now() - timedelta(days=5)).isoformat()
    index.record_ref(target_id=tid, ref_type="project_load", occurred_at=old)
    index.record_ref(target_id=tid, ref_type="project_load", occurred_at=recent)

    assert index.reference_count(tid, since_days=60) == 1   # excludes the 100d-old ref
    assert index.reference_count(tid, since_days=365) == 2  # window wide enough for both


# ---- #8 shared path classifiers ---------------------------------------


def test_kind_from_path() -> None:
    assert paths.kind_from_path("memories/working_memory.md") == "working"
    assert paths.kind_from_path("memories/long_term/people.md") == "long_term"
    assert paths.kind_from_path("memories/archived/old.md") == "archived"
    assert paths.kind_from_path("projects/Alpha/summary.md") == "project_summary"
    assert paths.kind_from_path("projects/Alpha/notes/kickoff.md") == "project_note"
    assert paths.kind_from_path("projects/Alpha/notes/deep/n.md") == "project_note"
    # Not part of the indexed set.
    assert paths.kind_from_path("system/logs/run.log") is None
    assert paths.kind_from_path("projects/Alpha") is None


def test_project_from_path() -> None:
    assert paths.project_from_path("projects/Alpha/summary.md") == "Alpha"
    assert paths.project_from_path("projects/Alpha/notes/n.md") == "Alpha"
    assert paths.project_from_path("memories/long_term/people.md") is None


# ---- #12 batched wikilink refs ----------------------------------------


def test_record_wikilink_refs_batches_and_noops_on_empty(
    vault: Path, index: Index
) -> None:
    for topic in ("a", "b", "c"):
        capture(vault, kind="long_term", topic=topic, content=topic.upper(), index=index)
    src = index.get_id("memories/long_term/a.md")
    b = index.get_id("memories/long_term/b.md")
    c = index.get_id("memories/long_term/c.md")
    assert None not in (src, b, c)

    index.record_wikilink_refs(src, [b, c])
    assert index.reference_count(b) == 1
    assert index.reference_count(c) == 1

    # Empty target set is a no-op, not an error.
    index.record_wikilink_refs(src, [])
    assert index.reference_count(b) == 1
