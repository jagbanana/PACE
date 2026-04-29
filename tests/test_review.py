"""Phase 5 weekly review: archival + wikilink validation + weekly synthesis."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from pace import frontmatter, projects
from pace import review as review_ops
from pace.capture import capture
from pace.index import Index
from pace.paths import ARCHIVED_DIR, LONG_TERM_DIR


def _seed_long_term(
    vault: Path,
    index: Index,
    *,
    topic: str,
    content: str,
    tags: list[str],
    date_modified: str,
) -> str:
    """Create a long_term/<topic>.md with a chosen date_modified, indexed."""
    capture(vault, kind="long_term", topic=topic, content=content, tags=tags, index=index)

    rel = f"{LONG_TERM_DIR}/{topic.lower()}.md"
    path = vault / rel
    text = path.read_text(encoding="utf-8")
    fm, body = frontmatter.parse(text)
    fm["date_modified"] = date_modified
    path.write_text(frontmatter.dump(fm, body), encoding="utf-8")
    record = index.get_by_path(rel)
    assert record is not None
    index.upsert_file(
        path=rel,
        kind="long_term",
        title=record.title,
        body=body,
        date_created=record.date_created,
        date_modified=date_modified,
        tags=record.tags,
    )
    return rel


# ---- Plan ------------------------------------------------------------


def test_plan_surfaces_stale_unreferenced_entries(vault: Path, index: Index) -> None:
    now = datetime(2026, 4, 27, 10, 0, 0)
    old_iso = (now - timedelta(days=120)).isoformat()
    rel = _seed_long_term(
        vault,
        index,
        topic="vendors",
        content="Acme is preferred for office supplies.",
        tags=["#business"],
        date_modified=old_iso,
    )

    plan = review_ops.plan_review(vault, index, now=now)
    paths = [c["path"] for c in plan["candidates"]]
    assert rel in paths


def test_plan_skips_recent_entries(vault: Path, index: Index) -> None:
    now = datetime(2026, 4, 27, 10, 0, 0)
    recent = (now - timedelta(days=30)).isoformat()
    _seed_long_term(
        vault,
        index,
        topic="vendors",
        content="Acme is preferred.",
        tags=["#business"],
        date_modified=recent,
    )
    plan = review_ops.plan_review(vault, index, now=now)
    assert plan["candidates"] == []


def test_plan_exempts_high_signal_decision_user_tags(
    vault: Path, index: Index
) -> None:
    """PRD §6.10 retention exemptions — these tags are never auto-archived,
    no matter how stale."""
    now = datetime(2026, 4, 27, 10, 0, 0)
    very_old = (now - timedelta(days=400)).isoformat()

    # Topic stays as the bare tag stem so capture's slugifier doesn't
    # rewrite the filename out from under us.
    for tag in ("#high-signal", "#decision", "#user"):
        topic = tag.lstrip("#")
        _seed_long_term(
            vault,
            index,
            topic=topic,
            content=f"Old entry tagged {tag}.",
            tags=[tag],
            date_modified=very_old,
        )

    plan = review_ops.plan_review(vault, index, now=now)
    # All three are exempt → no archival candidates.
    assert plan["candidates"] == []


def test_plan_skips_entries_with_recent_refs(vault: Path, index: Index) -> None:
    """An entry with a recent project_load ref must not be archived even
    if it's old."""
    now = datetime(2026, 4, 27, 10, 0, 0)
    very_old = (now - timedelta(days=400)).isoformat()
    rel = _seed_long_term(
        vault,
        index,
        topic="vendors",
        content="Old but recently referenced.",
        tags=["#business"],
        date_modified=very_old,
    )
    target_id = index.get_id(rel)
    assert target_id is not None
    index.record_ref(target_id=target_id, ref_type="project_load")

    plan = review_ops.plan_review(vault, index, now=now)
    assert plan["candidates"] == []


def test_plan_reports_broken_wikilinks(vault: Path, index: Index) -> None:
    projects.create_project(vault, "Alpha", index=index)
    capture(
        vault,
        kind="project_note",
        project="Alpha",
        note="refs",
        content="Pointing at [[Phantom]] which does not exist.",
        index=index,
    )
    plan = review_ops.plan_review(vault, index)
    targets = [b["target"] for b in plan["broken_wikilinks"]]
    assert "Phantom" in targets


# ---- Apply -----------------------------------------------------------


def test_apply_moves_approved_archives(vault: Path, index: Index) -> None:
    now = datetime(2026, 4, 27, 10, 0, 0)
    old_iso = (now - timedelta(days=120)).isoformat()
    rel = _seed_long_term(
        vault,
        index,
        topic="vendors",
        content="Acme — older preferred.",
        tags=["#business"],
        date_modified=old_iso,
    )

    plan = review_ops.plan_review(vault, index, now=now)
    plan["candidates"][0]["decision"] = "approve"

    result = review_ops.apply_review(vault, index, plan)
    assert result.archived == 1
    assert result.skipped == 0

    # Source gone, archived/<name>.md present.
    assert not (vault / rel).exists()
    archived = vault / ARCHIVED_DIR / "vendors.md"
    assert archived.is_file()

    # Index reflects the move.
    assert index.get_by_path(rel) is None
    new_record = index.get_by_path(f"{ARCHIVED_DIR}/vendors.md")
    assert new_record is not None
    assert new_record.kind == "archived"

    assert index.get_config("last_review") is not None
    assert result.log_path is not None
    assert result.log_path.is_file()


def test_apply_writes_weekly_synthesis_note(vault: Path, index: Index) -> None:
    plan = review_ops.plan_review(vault, index)
    plan["weekly_synthesis"] = (
        "## Themes\n\nThis week we shipped Phase 5 and tightened the prompts.\n"
    )

    result = review_ops.apply_review(vault, index, plan)
    assert result.weekly_note_written is True

    weekly_path = vault / plan["weekly_synthesis_target"]
    assert weekly_path.is_file()
    text = weekly_path.read_text(encoding="utf-8")
    assert "Phase 5" in text
    assert "weekly-synthesis" in text  # tag was applied


def test_apply_skips_when_synthesis_missing(vault: Path, index: Index) -> None:
    plan = review_ops.plan_review(vault, index)
    plan["weekly_synthesis"] = None  # LLM produced nothing

    result = review_ops.apply_review(vault, index, plan)
    assert result.weekly_note_written is False
    assert not (vault / plan["weekly_synthesis_target"]).exists()


def test_apply_rejects_wrong_plan_kind(vault: Path, index: Index) -> None:
    import pytest

    with pytest.raises(ValueError):
        review_ops.apply_review(vault, index, {"kind": "compact_plan"})
