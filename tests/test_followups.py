"""Tests for the followups data model + CRUD."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from pace import followups


def test_new_id_is_well_formed_and_unique() -> None:
    a = followups.new_id()
    b = followups.new_id()
    assert followups.is_valid_id(a)
    assert followups.is_valid_id(b)
    assert a != b


def test_add_followup_defaults_status_by_trigger(vault: Path) -> None:
    """date trigger → pending; manual/stale/pattern → ready."""
    fu_date = followups.add_followup(
        vault, body="dated", trigger="date", trigger_value="2030-01-01"
    )
    fu_manual = followups.add_followup(vault, body="manual", trigger="manual")
    fu_stale = followups.add_followup(vault, body="stale", trigger="stale")

    assert fu_date.status == "pending"
    assert fu_manual.status == "ready"
    assert fu_stale.status == "ready"


def test_add_followup_rejects_invalid_trigger(vault: Path) -> None:
    with pytest.raises(ValueError, match="Invalid trigger"):
        followups.add_followup(vault, body="x", trigger="banana")


def test_add_followup_rejects_invalid_priority(vault: Path) -> None:
    with pytest.raises(ValueError, match="Invalid priority"):
        followups.add_followup(
            vault, body="x", trigger="manual", priority="urgent"
        )


def test_followup_file_lands_under_followups_dir(vault: Path) -> None:
    fu = followups.add_followup(vault, body="hi", trigger="manual")
    target = vault / "followups" / f"{fu.id}.md"
    assert target.is_file()
    text = target.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "kind: followup" in text
    assert "hi" in text


def test_list_followups_filters_by_status_and_project(vault: Path) -> None:
    a = followups.add_followup(vault, body="a", trigger="manual", project="x")
    b = followups.add_followup(vault, body="b", trigger="manual", project="y")
    c = followups.add_followup(  # noqa: F841 — used implicitly via filter
        vault, body="c", trigger="date", trigger_value="2030-01-01"
    )

    by_proj = followups.list_followups(vault, project="x")
    assert [f.id for f in by_proj] == [a.id]

    ready_only = followups.list_followups(vault, status="ready")
    assert {f.id for f in ready_only} == {a.id, b.id}

    pending_only = followups.list_followups(vault, status="pending")
    assert len(pending_only) == 1
    assert pending_only[0].trigger == "date"


def test_resolve_moves_to_done_dir(vault: Path) -> None:
    fu = followups.add_followup(vault, body="x", trigger="manual")
    active_path = vault / "followups" / f"{fu.id}.md"
    assert active_path.is_file()

    resolved = followups.resolve_followup(vault, fu.id, status="done")
    assert resolved is not None
    assert resolved.status == "done"
    assert not active_path.is_file()
    assert (vault / "followups" / "done" / f"{fu.id}.md").is_file()


def test_resolve_returns_none_for_missing_id(vault: Path) -> None:
    assert followups.resolve_followup(vault, "f-99990101-000000-000000") is None


def test_resolve_rejects_active_status(vault: Path) -> None:
    fu = followups.add_followup(vault, body="x", trigger="manual")
    with pytest.raises(ValueError):
        followups.resolve_followup(vault, fu.id, status="ready")


def test_update_status_flips_pending_to_ready_in_place(vault: Path) -> None:
    fu = followups.add_followup(
        vault, body="x", trigger="date", trigger_value="2030-01-01"
    )
    assert fu.status == "pending"
    updated = followups.update_status(vault, fu.id, status="ready")
    assert updated is not None
    assert updated.status == "ready"
    # Still in active dir, not done dir.
    assert (vault / "followups" / f"{fu.id}.md").is_file()
    assert not (vault / "followups" / "done" / f"{fu.id}.md").is_file()


def test_update_status_rejects_terminal_states(vault: Path) -> None:
    fu = followups.add_followup(vault, body="x", trigger="manual")
    with pytest.raises(ValueError):
        followups.update_status(vault, fu.id, status="done")


def test_evaluate_date_triggers_returns_only_ripe_pending(vault: Path) -> None:
    today = datetime.now().date()
    ripe = followups.add_followup(
        vault,
        body="due yesterday",
        trigger="date",
        trigger_value=(today - timedelta(days=1)).isoformat(),
    )
    not_yet = followups.add_followup(  # noqa: F841 — referenced via filter
        vault,
        body="due in a year",
        trigger="date",
        trigger_value=(today + timedelta(days=365)).isoformat(),
    )
    # Manual trigger should never appear here.
    followups.add_followup(vault, body="manual", trigger="manual")

    out = followups.evaluate_date_triggers(vault)
    assert [f.id for f in out] == [ripe.id]


def test_inbox_for_status_orders_by_priority(vault: Path) -> None:
    low = followups.add_followup(vault, body="low", trigger="manual", priority="low")
    high = followups.add_followup(
        vault, body="high", trigger="manual", priority="high"
    )
    normal = followups.add_followup(  # noqa: F841 — used in IDs check
        vault, body="normal", trigger="manual"
    )

    inbox = followups.inbox_for_status(vault)
    ids = [item["id"] for item in inbox]
    # high first, then normal, then low
    assert ids[0] == high.id
    assert ids[-1] == low.id


def test_inbox_excludes_pending_and_done(vault: Path) -> None:
    followups.add_followup(
        vault, body="pending", trigger="date", trigger_value="2030-01-01"
    )
    ready = followups.add_followup(vault, body="ready", trigger="manual")
    done = followups.add_followup(vault, body="done", trigger="manual")
    followups.resolve_followup(vault, done.id)

    inbox = followups.inbox_for_status(vault)
    assert [i["id"] for i in inbox] == [ready.id]


def test_read_followup_finds_active_or_done(vault: Path) -> None:
    fu = followups.add_followup(vault, body="x", trigger="manual")
    assert followups.read_followup(vault, fu.id) is not None
    followups.resolve_followup(vault, fu.id)
    found = followups.read_followup(vault, fu.id)
    assert found is not None
    assert found.status == "done"


def test_corrupt_frontmatter_is_skipped_not_raised(vault: Path) -> None:
    """An ill-formed file in followups/ shouldn't crash inbox reads —
    operational state needs to degrade gracefully."""
    bad = vault / "followups" / "f-20260101-000000-deadbe.md"
    bad.write_text("---\nnot: [valid yaml: ohno\n---\nbody\n", encoding="utf-8")
    # Should not raise.
    items = followups.list_followups(vault)
    # The malformed file is skipped; well-formed siblings still load.
    fu = followups.add_followup(vault, body="ok", trigger="manual")
    items = followups.list_followups(vault)
    assert any(f.id == fu.id for f in items)
