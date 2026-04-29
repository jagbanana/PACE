"""Tests for the proactive heartbeat orchestrator."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from pace import followups, heartbeat
from pace import settings as pace_settings
from pace.frontmatter import dump as fm_dump
from pace.frontmatter import parse as fm_parse
from pace.index import Index
from pace.io import atomic_write_text
from pace.paths import WORKING_MEMORY

# ---- helpers ---------------------------------------------------------


def _enable_heartbeat(vault: Path, **overrides: str) -> None:
    """Drop a config that turns the heartbeat on with permissive defaults."""
    cfg = (
        "heartbeat:\n"
        "  enabled: true\n"
        f"  working_hours_start: \"{overrides.get('start', '00:00')}\"\n"
        f"  working_hours_end:   \"{overrides.get('end', '23:59')}\"\n"
        "  working_days: [mon, tue, wed, thu, fri, sat, sun]\n"
        f"  cadence_minutes: {overrides.get('cadence', '0')}\n"
        f"  stale_age_days: {overrides.get('stale_age', '7')}\n"
        f"  pattern_min_repeats: {overrides.get('pattern_min', '3')}\n"
    )
    (vault / "system" / "pace_config.yaml").write_text(cfg, encoding="utf-8")


def _append_wm_entry(
    vault: Path,
    *,
    timestamp: datetime,
    tags: list[str],
    body: str,
) -> None:
    """Append an entry directly into working_memory.md (bypass capture for
    deterministic test setup)."""
    path = vault / WORKING_MEMORY
    text = path.read_text(encoding="utf-8")
    fm, current_body = fm_parse(text)
    tag_str = " ".join(tags)
    heading = f"## {timestamp.strftime('%Y-%m-%d %H:%M')} — {tag_str}".rstrip(" —")
    addition = f"{heading}\n\n{body.rstrip()}\n"
    new_body = (current_body.rstrip() + "\n\n" + addition) if current_body.strip() else addition
    fm["date_modified"] = datetime.now().isoformat(timespec="seconds")
    atomic_write_text(path, fm_dump(fm, new_body))


# ---- run-window guard -----------------------------------------------


def test_should_run_blocks_when_disabled() -> None:
    s = pace_settings.Settings()
    decision = heartbeat.should_run(s, last_run_iso=None)
    assert not decision.run
    assert decision.reason == "heartbeat_disabled"


def test_should_run_blocks_outside_working_hours() -> None:
    s = pace_settings.Settings(
        heartbeat_enabled=True,
        heartbeat_start="09:00",
        heartbeat_end="17:00",
        heartbeat_days=("mon", "tue", "wed", "thu", "fri", "sat", "sun"),
    )
    midnight = datetime(2026, 4, 29, 3, 0)
    decision = heartbeat.should_run(s, last_run_iso=None, now=midnight)
    assert not decision.run
    assert "outside_working_hours" in decision.reason


def test_should_run_blocks_outside_working_days() -> None:
    s = pace_settings.Settings(
        heartbeat_enabled=True,
        heartbeat_days=("mon",),
        heartbeat_start="00:00",
        heartbeat_end="23:59",
    )
    # 2026-04-29 is a Wednesday, not Monday.
    wed = datetime(2026, 4, 29, 12, 0)
    decision = heartbeat.should_run(s, last_run_iso=None, now=wed)
    assert not decision.run
    assert "outside_working_days" in decision.reason


def test_should_run_blocks_under_cadence() -> None:
    s = pace_settings.Settings(
        heartbeat_enabled=True,
        heartbeat_start="00:00",
        heartbeat_end="23:59",
        heartbeat_days=("mon", "tue", "wed", "thu", "fri", "sat", "sun"),
        heartbeat_cadence_minutes=60,
    )
    now = datetime(2026, 4, 29, 12, 0)
    last = (now - timedelta(minutes=10)).isoformat()
    decision = heartbeat.should_run(s, last_run_iso=last, now=now)
    assert not decision.run
    assert "under_cadence" in decision.reason


def test_should_run_passes_when_all_conditions_met() -> None:
    s = pace_settings.Settings(
        heartbeat_enabled=True,
        heartbeat_start="00:00",
        heartbeat_end="23:59",
        heartbeat_days=("mon", "tue", "wed", "thu", "fri", "sat", "sun"),
        heartbeat_cadence_minutes=0,
    )
    decision = heartbeat.should_run(s, last_run_iso=None)
    assert decision.run
    assert decision.reason == "ok"


# ---- plan ------------------------------------------------------------


def test_plan_returns_no_op_when_disabled(vault: Path, index: Index) -> None:
    plan = heartbeat.plan_heartbeat(vault, index)
    assert plan["kind"] == "heartbeat_plan"
    assert plan["run"] is False
    assert plan["skip_reason"] == "heartbeat_disabled"
    assert plan["ripe_date_triggers"] == []
    assert plan["stale_candidates"] == []
    assert plan["pattern_candidates"] == []


def test_plan_surfaces_ripe_date_triggers(vault: Path, index: Index) -> None:
    _enable_heartbeat(vault)
    today = datetime.now().date()
    ripe = followups.add_followup(
        vault,
        body="legal review",
        trigger="date",
        trigger_value=(today - timedelta(days=1)).isoformat(),
    )
    # Future date: should NOT be ripe.
    followups.add_followup(
        vault,
        body="next year",
        trigger="date",
        trigger_value=(today + timedelta(days=365)).isoformat(),
    )

    plan = heartbeat.plan_heartbeat(vault, index)
    assert plan["run"] is True
    ids = [c["id"] for c in plan["ripe_date_triggers"]]
    assert ids == [ripe.id]


def test_plan_surfaces_stale_commitments(vault: Path, index: Index) -> None:
    _enable_heartbeat(vault)
    old = datetime.now() - timedelta(days=14)
    _append_wm_entry(
        vault,
        timestamp=old,
        tags=["#decision"],
        body="TODO: ping legal about the redline before the launch.",
    )
    plan = heartbeat.plan_heartbeat(vault, index)
    assert plan["run"] is True
    assert len(plan["stale_candidates"]) == 1
    cand = plan["stale_candidates"][0]
    assert "redline" in cand["body_excerpt"]
    assert cand["age_days"] >= 7


def test_stale_skipped_when_followthrough_exists(
    vault: Path, index: Index
) -> None:
    """A newer entry sharing tags counts as follow-through."""
    _enable_heartbeat(vault)
    old = datetime.now() - timedelta(days=14)
    newer = datetime.now() - timedelta(days=3)
    _append_wm_entry(
        vault,
        timestamp=old,
        tags=["#decision"],
        body="TODO: write the press release",
    )
    _append_wm_entry(
        vault,
        timestamp=newer,
        tags=["#decision"],
        body="Press release first draft is up.",
    )
    plan = heartbeat.plan_heartbeat(vault, index)
    assert plan["stale_candidates"] == []


def test_plan_surfaces_repeated_person_mentions(
    vault: Path, index: Index
) -> None:
    _enable_heartbeat(vault, pattern_min="3")
    now = datetime.now()
    for i in range(4):
        _append_wm_entry(
            vault,
            timestamp=now - timedelta(days=i),
            tags=["#user"],
            body=f"Spoke with Sasha Reyes again about pricing #{i}.",
        )
    plan = heartbeat.plan_heartbeat(vault, index)
    pat = plan["pattern_candidates"]
    person_pats = [p for p in pat if p.get("kind") == "person_repeat"]
    assert any("Sasha Reyes" in p["subject"] for p in person_pats)


def test_pattern_skips_known_people(vault: Path, index: Index) -> None:
    _enable_heartbeat(vault, pattern_min="3")
    # Pre-seed long_term/people.md so Sasha is "known."
    people = vault / "memories" / "long_term" / "people.md"
    people.parent.mkdir(parents=True, exist_ok=True)
    people.write_text(
        "---\ntitle: People\nkind: long_term\n---\n\n"
        "## 2026-04-01 09:00 — #person\n\nSasha Reyes is the COO.\n",
        encoding="utf-8",
    )
    now = datetime.now()
    for i in range(4):
        _append_wm_entry(
            vault,
            timestamp=now - timedelta(days=i),
            tags=["#user"],
            body=f"Spoke with Sasha Reyes again about pricing #{i}.",
        )
    plan = heartbeat.plan_heartbeat(vault, index)
    person_pats = [
        p
        for p in plan["pattern_candidates"]
        if p.get("kind") == "person_repeat"
    ]
    assert person_pats == []


# ---- apply -----------------------------------------------------------


def test_apply_promotes_approved_ripe(vault: Path, index: Index) -> None:
    _enable_heartbeat(vault)
    today = datetime.now().date()
    fu = followups.add_followup(
        vault,
        body="legal review",
        trigger="date",
        trigger_value=(today - timedelta(days=1)).isoformat(),
    )

    plan = heartbeat.plan_heartbeat(vault, index)
    plan["ripe_date_triggers"][0]["decision"] = "approve"

    result = heartbeat.apply_heartbeat(vault, index, plan)
    assert result.ripe_promoted == 1
    assert result.skipped_run is False
    assert result.log_path is not None and result.log_path.is_file()

    # The followup now ready and shows up in the inbox.
    refreshed = followups.read_followup(vault, fu.id)
    assert refreshed is not None and refreshed.status == "ready"


def test_apply_creates_followups_for_approved_stale(
    vault: Path, index: Index
) -> None:
    _enable_heartbeat(vault)
    _append_wm_entry(
        vault,
        timestamp=datetime.now() - timedelta(days=14),
        tags=["#decision"],
        body="TODO: ping legal about the redline.",
    )
    plan = heartbeat.plan_heartbeat(vault, index)
    plan["stale_candidates"][0]["decision"] = "approve"
    plan["stale_candidates"][0]["body"] = "Legal redline is overdue — ping them."

    result = heartbeat.apply_heartbeat(vault, index, plan)
    assert result.stale_created == 1
    inbox = followups.inbox_for_status(vault)
    assert any("Legal redline" in i["body"] for i in inbox)


def test_apply_rejects_wrong_kind(vault: Path, index: Index) -> None:
    with pytest.raises(ValueError, match="Expected heartbeat_plan"):
        heartbeat.apply_heartbeat(vault, index, {"kind": "compact_plan"})


def test_apply_no_op_records_last_heartbeat(vault: Path, index: Index) -> None:
    """When run=false, apply should still bump last_heartbeat so the
    cadence guard sees forward progress and the run is logged."""
    plan = heartbeat.plan_heartbeat(vault, index)
    assert plan["run"] is False
    result = heartbeat.apply_heartbeat(vault, index, plan)
    assert result.skipped_run is True
    assert result.skip_reason == "heartbeat_disabled"
    assert index.get_config("last_heartbeat") is not None


def test_apply_skips_unapproved_candidates(vault: Path, index: Index) -> None:
    _enable_heartbeat(vault)
    today = datetime.now().date()
    followups.add_followup(
        vault,
        body="x",
        trigger="date",
        trigger_value=(today - timedelta(days=1)).isoformat(),
    )
    plan = heartbeat.plan_heartbeat(vault, index)
    # Leave decision as "pending" — should be skipped.
    result = heartbeat.apply_heartbeat(vault, index, plan)
    assert result.ripe_promoted == 0
    assert result.skipped == 1
