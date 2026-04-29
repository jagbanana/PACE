"""Vault health checks — one test per finding type plus end-to-end."""

from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from pace import doctor as doctor_ops
from pace import projects as project_ops
from pace.capture import capture
from pace.index import Index
from pace.paths import INDEX_DB, LONG_TERM_DIR, WORKING_MEMORY

# ---- Healthy baseline --------------------------------------------------


def test_healthy_vault_has_no_warnings(vault: Path, index: Index) -> None:
    """A freshly-init'd vault stamps ``vault_created_at`` so doctor
    suppresses the never-run warnings during the day-1 exemption window.
    The model shouldn't nag the user about scheduled tasks before they've
    even had a chance to fire."""
    report = doctor_ops.run_all(vault, index)
    assert report.errors == []
    assert report.warnings == []


# ---- DB integrity -----------------------------------------------------


def test_db_integrity_passes_on_fresh_db(vault: Path, index: Index) -> None:
    issues = doctor_ops.check_db_integrity(index)
    assert issues == []


def test_db_integrity_detects_corruption(vault: Path) -> None:
    """Smash a header byte, then run the check.

    Severe corruption can prevent the DB from opening at all — that's a
    valid positive signal too. Either path proves the integrity check
    surfaces the failure rather than letting writes silently corrupt
    the index further.
    """
    db_path = vault / INDEX_DB
    with open(db_path, "r+b") as fh:
        fh.seek(100)  # somewhere inside SQLite's first page
        fh.write(b"\x00" * 32)

    idx: Index | None = None
    try:
        idx = Index(db_path)
    except sqlite3.DatabaseError:
        # Corruption fatal enough that even opening raises. Doctor will
        # surface this through the same code-path as `db-integrity-failed`
        # when called from a higher level (the CLI catches it).
        return

    try:
        issues = doctor_ops.check_db_integrity(idx)
        assert issues, "Expected integrity_check to flag corruption."
        assert issues[0].code in {"db-corruption", "db-integrity-failed"}
    finally:
        idx.close()


# ---- Index drift -------------------------------------------------------


def test_index_drift_flags_externally_modified_files(
    vault: Path, index: Index
) -> None:
    capture(vault, kind="working", content="Initial entry.", index=index)

    # Edit working_memory.md directly and bump its mtime forward.
    wm = vault / WORKING_MEMORY
    wm.write_text(
        wm.read_text(encoding="utf-8") + "\n## 2026-04-27 12:00\n\nSneaky edit.\n",
        encoding="utf-8",
    )
    future = time.time() + 600  # 10 min into the future, comfortably past 60s tolerance
    os.utime(wm, (future, future))

    issues = doctor_ops.check_index_drift(vault, index)
    assert any(i.code == "index-drift" for i in issues)
    drifted = next(i for i in issues if i.code == "index-drift")
    assert WORKING_MEMORY in (drifted.detail or "")


def test_index_drift_clean_when_in_sync(vault: Path, index: Index) -> None:
    capture(vault, kind="working", content="A note.", index=index)
    # No external edits → no drift.
    issues = doctor_ops.check_index_drift(vault, index)
    assert issues == []


# ---- Broken wikilinks --------------------------------------------------


def test_broken_wikilinks_detected(vault: Path, index: Index) -> None:
    project_ops.create_project(vault, "Alpha", index=index)
    capture(
        vault,
        kind="project_note",
        project="Alpha",
        note="cross",
        content="See [[Phantom]] which does not exist.",
        index=index,
    )
    issues = doctor_ops.check_broken_wikilinks(vault, index)
    assert any(i.code == "broken-wikilinks" for i in issues)
    issue = next(i for i in issues if i.code == "broken-wikilinks")
    assert "Phantom" in (issue.detail or "")


def test_broken_wikilinks_clean_when_all_resolve(
    vault: Path, index: Index
) -> None:
    project_ops.create_project(vault, "Alpha", index=index)
    project_ops.create_project(vault, "Beta", index=index)
    capture(
        vault,
        kind="project_note",
        project="Alpha",
        note="cross",
        content="Linking to [[Beta]] which exists.",
        index=index,
    )
    issues = doctor_ops.check_broken_wikilinks(vault, index)
    assert issues == []


# ---- Conflicted copies -------------------------------------------------


def test_conflicted_copies_detected(vault: Path) -> None:
    bad = vault / LONG_TERM_DIR / "people (Conflicted Copy 2026-04-15).md"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("conflict version", encoding="utf-8")

    issues = doctor_ops.check_conflicted_copies(vault)
    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert "Conflicted" in (issues[0].detail or "")


def test_conflicted_copies_clean(vault: Path) -> None:
    assert doctor_ops.check_conflicted_copies(vault) == []


# ---- Scheduled-task freshness -----------------------------------------


def test_scheduled_task_freshness_warns_on_never_run(
    vault: Path, index: Index
) -> None:
    """Outside the day-1 exemption window, never-run is a warning."""
    # Backdate the vault so the exemption no longer applies.
    old_creation = (datetime.now() - timedelta(days=30)).isoformat()
    index.set_config("vault_created_at", old_creation)

    issues = doctor_ops.check_scheduled_task_freshness(index)
    codes = {i.code for i in issues}
    assert "last-compact-never" in codes
    assert "last-review-never" in codes


def test_scheduled_task_freshness_silent_during_day_one_exemption(
    vault: Path, index: Index
) -> None:
    """Brand-new vault: never-run warnings are suppressed."""
    issues = doctor_ops.check_scheduled_task_freshness(index)
    assert issues == []


def test_scheduled_task_freshness_warns_on_stale_compact(
    vault: Path, index: Index
) -> None:
    now = datetime(2026, 4, 27, 10, 0, 0)
    stale = (now - timedelta(hours=72)).isoformat()
    index.set_config("last_compact", stale)
    index.set_config("last_review", now.isoformat())

    issues = doctor_ops.check_scheduled_task_freshness(index, now=now)
    codes = {i.code for i in issues}
    assert "last-compact-stale" in codes
    assert "last-review-stale" not in codes


def test_scheduled_task_freshness_clean_when_recent(
    vault: Path, index: Index
) -> None:
    now = datetime(2026, 4, 27, 10, 0, 0)
    index.set_config("last_compact", (now - timedelta(hours=12)).isoformat())
    index.set_config("last_review", (now - timedelta(days=3)).isoformat())

    issues = doctor_ops.check_scheduled_task_freshness(index, now=now)
    assert issues == []


# ---- Top-level run_all + serialization --------------------------------


def test_run_all_aggregates_issues(vault: Path, index: Index) -> None:
    # Seed a conflicted-copy and a broken wikilink.
    bad = vault / LONG_TERM_DIR / "vendors (Conflicted Copy 2026-04-15).md"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("conflict", encoding="utf-8")
    project_ops.create_project(vault, "Alpha", index=index)
    capture(
        vault,
        kind="project_note",
        project="Alpha",
        note="cross",
        content="See [[NeverDefined]].",
        index=index,
    )

    report = doctor_ops.run_all(vault, index)
    assert not report.healthy
    codes = {i.code for i in report.issues}
    assert "conflicted-copies" in codes
    assert "broken-wikilinks" in codes


def test_report_to_warnings_renders_one_line_per_issue() -> None:
    report = doctor_ops.HealthReport(
        root=Path("."),
        issues=[
            doctor_ops.HealthIssue(
                severity="error",
                code="x",
                message="A thing broke.",
                detail="d",
                fix_hint="run pace fix",
            ),
            doctor_ops.HealthIssue(severity="info", code="y", message="info-only"),
        ],
    )
    lines = doctor_ops.report_to_warnings(report)
    assert len(lines) == 1
    assert "A thing broke" in lines[0]
    assert "[error]" in lines[0]
    assert "info-only" not in lines[0]


# ---- pytest skip marker for OneDrive (manual check) -------------------


@pytest.mark.skipif(
    not hasattr(os.stat_result, "st_file_attributes"),
    reason="st_file_attributes is Windows-only.",
)
def test_onedrive_check_clean_on_local_dir(vault: Path) -> None:
    """Tmpdirs aren't OneDrive-virtualized, so this should always pass."""
    issues = doctor_ops.check_onedrive_virtualized(vault)
    assert issues == []


# ---- Working-memory size check ---------------------------------------


def _settings_with_caps(soft: int, hard: int):
    """Build a Settings object directly so the test isn't coupled to
    the yaml loader path."""
    from pace.settings import Settings

    return Settings(working_memory_soft_chars=soft, working_memory_hard_chars=hard)


def test_working_memory_size_clean_under_soft(vault: Path) -> None:
    """Tiny vault, generous caps → no warning."""
    settings = _settings_with_caps(soft=10_000, hard=20_000)
    issues = doctor_ops.check_working_memory_size(vault, settings)
    assert issues == []


def test_working_memory_size_warns_over_soft(vault: Path) -> None:
    """Body exceeds soft cap but not hard cap → warning."""
    from pace import frontmatter as fm_mod

    wm = vault / WORKING_MEMORY
    fm, _ = fm_mod.parse(wm.read_text(encoding="utf-8"))
    big_body = "## 2026-01-01 00:00\n\n" + ("padding " * 100)  # ~800 chars
    wm.write_text(fm_mod.dump(fm, big_body), encoding="utf-8")

    settings = _settings_with_caps(soft=200, hard=2_000)
    issues = doctor_ops.check_working_memory_size(vault, settings)
    assert len(issues) == 1
    assert issues[0].code == "working-memory-oversize"
    assert issues[0].severity == "warning"


def test_working_memory_size_errors_over_hard(vault: Path) -> None:
    """Body exceeds hard cap → error (not just warning), with detail
    explaining that pace_status will truncate."""
    from pace import frontmatter as fm_mod

    wm = vault / WORKING_MEMORY
    fm, _ = fm_mod.parse(wm.read_text(encoding="utf-8"))
    very_big_body = "## 2026-01-01 00:00\n\n" + ("padding " * 200)
    wm.write_text(fm_mod.dump(fm, very_big_body), encoding="utf-8")

    settings = _settings_with_caps(soft=200, hard=400)
    issues = doctor_ops.check_working_memory_size(vault, settings)
    assert len(issues) == 1
    assert issues[0].code == "working-memory-oversize"
    assert issues[0].severity == "error"
    assert issues[0].detail is not None
    assert "truncates" in issues[0].detail.lower()
