"""Phase 5 daily compaction: plan generation and apply."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from pace import compact as compact_ops
from pace import frontmatter, projects
from pace.capture import capture
from pace.index import Index
from pace.paths import LONG_TERM_DIR, WORKING_MEMORY


def _write_working_entry(
    vault: Path,
    *,
    when: datetime,
    tags: list[str],
    content: str,
) -> str:
    """Append a hand-crafted entry to working_memory.md with a specific
    timestamp so we can drive the age-based promotion rules deterministically.
    Returns the entry's heading (used to look it up in the plan)."""
    wm = vault / WORKING_MEMORY
    text = wm.read_text(encoding="utf-8")
    fm, body = frontmatter.parse(text)
    tag_str = " ".join(tags)
    heading = f"## {when.strftime('%Y-%m-%d %H:%M')}{(' — ' + tag_str) if tag_str else ''}"
    new_block = f"{heading}\n\n{content}\n"
    body = (body.rstrip() + "\n\n" + new_block) if body.strip() else new_block
    fm["date_modified"] = when.isoformat()
    wm.write_text(frontmatter.dump(fm, body), encoding="utf-8")
    return heading


# ---- Plan -------------------------------------------------------------


def test_plan_promotes_old_tagged_entries(vault: Path, index: Index) -> None:
    now = datetime(2026, 4, 27, 10, 0, 0)
    old = now - timedelta(days=10)

    heading = _write_working_entry(
        vault,
        when=old,
        tags=["#person", "#user"],
        content="Alex is the user's COO; prefers brevity.",
    )

    plan = compact_ops.plan_compaction(vault, index, now=now)
    assert plan["kind"] == "compact_plan"
    assert len(plan["candidates"]) == 1
    cand = plan["candidates"][0]
    assert cand["action"] == "promote"
    assert cand["decision"] == "pending"
    assert cand["source_heading"] == heading
    assert cand["tags"] == ["#person", "#user"]
    assert cand["suggested_topic"] == "people"


def test_plan_skips_entries_too_recent(vault: Path, index: Index) -> None:
    now = datetime(2026, 4, 27, 10, 0, 0)
    fresh = now - timedelta(days=2)

    _write_working_entry(
        vault,
        when=fresh,
        tags=["#preference"],  # not in long-term tag set; needs age
        content="A recent preference. Not promotable yet.",
    )
    plan = compact_ops.plan_compaction(vault, index, now=now)
    assert plan["candidates"] == []


def test_plan_promotes_long_term_tag_even_when_recent(
    vault: Path, index: Index
) -> None:
    """Tags in _LONG_TERM_TAGS bypass the age requirement."""
    now = datetime(2026, 4, 27, 10, 0, 0)
    fresh = now - timedelta(hours=2)

    _write_working_entry(
        vault,
        when=fresh,
        tags=["#decision"],
        content="User decided to ship internally before public release.",
    )
    plan = compact_ops.plan_compaction(vault, index, now=now)
    assert len(plan["candidates"]) == 1
    assert plan["candidates"][0]["suggested_topic"] == "decisions"


def test_plan_includes_active_projects_with_recent_activity(
    vault: Path, index: Index
) -> None:
    projects.create_project(vault, "Alpha", index=index)
    capture(
        vault,
        kind="project_summary",
        project="Alpha",
        content="Kickoff Monday.",
        index=index,
    )
    now = datetime.now() + timedelta(hours=1)  # ensure cutoff includes us
    plan = compact_ops.plan_compaction(vault, index, now=now)
    names = [p["project"] for p in plan["active_projects_with_activity"]]
    assert "Alpha" in names


# ---- Apply ------------------------------------------------------------


def test_apply_promotes_approved_candidate(vault: Path, index: Index) -> None:
    now = datetime(2026, 4, 27, 10, 0, 0)
    old = now - timedelta(days=10)
    heading = _write_working_entry(
        vault,
        when=old,
        tags=["#person"],
        content="Alex is the user's COO.",
    )

    plan = compact_ops.plan_compaction(vault, index, now=now)
    assert len(plan["candidates"]) == 1
    plan["candidates"][0]["decision"] = "approve"

    result = compact_ops.apply_compaction(vault, index, plan)
    assert result.promoted == 1
    assert result.skipped == 0

    # Working memory no longer contains the entry's body.
    wm_text = (vault / WORKING_MEMORY).read_text(encoding="utf-8")
    assert "Alex is the user's COO." not in wm_text

    # long_term/people.md was created and contains the promoted content
    # along with the original heading (the timestamp is preserved).
    people = vault / LONG_TERM_DIR / "people.md"
    assert people.is_file()
    body = people.read_text(encoding="utf-8")
    assert heading in body
    assert "Alex is the user's COO." in body

    # Index reflects both files.
    assert index.get_by_path(WORKING_MEMORY) is not None
    assert index.get_by_path("memories/long_term/people.md") is not None

    # Last-compact config bumped.
    assert index.get_config("last_compact") is not None

    # Log was written.
    assert result.log_path is not None
    assert result.log_path.is_file()


def test_apply_skips_pending_and_skip_decisions(vault: Path, index: Index) -> None:
    now = datetime(2026, 4, 27, 10, 0, 0)
    old = now - timedelta(days=10)
    _write_working_entry(
        vault,
        when=old,
        tags=["#person"],
        content="Should stay in working memory.",
    )

    plan = compact_ops.plan_compaction(vault, index, now=now)
    plan["candidates"][0]["decision"] = "skip"

    result = compact_ops.apply_compaction(vault, index, plan)
    assert result.promoted == 0
    assert result.skipped == 1

    wm_text = (vault / WORKING_MEMORY).read_text(encoding="utf-8")
    assert "Should stay in working memory." in wm_text


def test_apply_overrides_topic_via_decision(vault: Path, index: Index) -> None:
    now = datetime(2026, 4, 27, 10, 0, 0)
    old = now - timedelta(days=10)
    _write_working_entry(
        vault,
        when=old,
        tags=["#person"],
        content="Alex is COO.",
    )

    plan = compact_ops.plan_compaction(vault, index, now=now)
    cand = plan["candidates"][0]
    cand["decision"] = "approve"
    cand["topic"] = "leadership"  # override 'people' default

    compact_ops.apply_compaction(vault, index, plan)
    assert (vault / LONG_TERM_DIR / "leadership.md").is_file()
    assert not (vault / LONG_TERM_DIR / "people.md").exists()


def test_apply_rejects_wrong_plan_kind(vault: Path, index: Index) -> None:
    import pytest

    with pytest.raises(ValueError):
        compact_ops.apply_compaction(vault, index, {"kind": "review_plan"})


# ---- Force-promotion (working-memory size enforcement) ---------------


def _write_tight_settings(vault: Path, soft: int, hard: int) -> None:
    """Write a pace_config.yaml that makes the soft cap easy to trip."""
    cfg = vault / "system" / "pace_config.yaml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(
        f"working_memory:\n  soft_chars: {soft}\n  hard_chars: {hard}\n",
        encoding="utf-8",
    )


def test_apply_force_promotes_when_over_soft_cap(vault: Path, index: Index) -> None:
    """If working memory is still over the soft cap after the LLM's
    decisions are applied, the apply step force-promotes oldest entries
    to long_term/working-overflow.md until the body fits."""
    _write_tight_settings(vault, soft=300, hard=1000)
    now = datetime(2026, 4, 27, 10, 0, 0)

    # Write 5 entries, oldest first; each ~120 chars so 5 entries blow
    # past a 300-char soft cap.
    for i in range(5):
        when = now - timedelta(days=10 + i)
        _write_working_entry(
            vault,
            when=when,
            tags=["#fact"],
            content=f"Entry {i}: padding text padding text padding text padding text.",
        )

    plan = compact_ops.plan_compaction(vault, index, now=now)
    # Skip every candidate so the LLM doesn't trigger normal promotions.
    for cand in plan["candidates"]:
        cand["decision"] = "skip"

    result = compact_ops.apply_compaction(vault, index, plan)

    assert result.overflow_promoted >= 1, (
        f"Expected force-promotion when body exceeds soft cap, "
        f"got overflow_promoted={result.overflow_promoted}"
    )

    overflow = vault / LONG_TERM_DIR / "working-overflow.md"
    assert overflow.is_file(), "force-promoted entries should land in working-overflow.md"

    # Working memory body should now fit under the soft cap.
    from pace import frontmatter as fm_mod
    wm_text = (vault / WORKING_MEMORY).read_text(encoding="utf-8")
    _, wm_body = fm_mod.parse(wm_text)
    assert len(wm_body) <= 300, (
        f"Body still over soft cap after apply: {len(wm_body)} chars"
    )


def test_apply_does_not_force_promote_when_under_soft_cap(
    vault: Path, index: Index
) -> None:
    """Normal-sized working memory shouldn't trigger overflow logic."""
    _write_tight_settings(vault, soft=10_000, hard=20_000)
    now = datetime(2026, 4, 27, 10, 0, 0)
    _write_working_entry(
        vault,
        when=now - timedelta(days=2),
        tags=["#fact"],
        content="A small note.",
    )

    plan = compact_ops.plan_compaction(vault, index, now=now)
    for cand in plan["candidates"]:
        cand["decision"] = "skip"
    result = compact_ops.apply_compaction(vault, index, plan)

    assert result.overflow_promoted == 0
    assert not (vault / LONG_TERM_DIR / "working-overflow.md").exists()


def test_apply_force_promotion_keeps_newest_entries(vault: Path, index: Index) -> None:
    """Force-promotion sorts oldest-first; newest entries must survive."""
    _write_tight_settings(vault, soft=200, hard=800)
    now = datetime(2026, 4, 27, 10, 0, 0)

    headings = []
    for i in range(4):
        when = now - timedelta(days=10 + i)
        h = _write_working_entry(
            vault,
            when=when,
            tags=["#fact"],
            content=f"Entry {i}: padding padding padding padding padding.",
        )
        headings.append(h)

    plan = compact_ops.plan_compaction(vault, index, now=now)
    for cand in plan["candidates"]:
        cand["decision"] = "skip"
    compact_ops.apply_compaction(vault, index, plan)

    wm_text = (vault / WORKING_MEMORY).read_text(encoding="utf-8")
    # The very newest entry (i=0, 10 days ago) is the most recent in
    # this fixture; it should survive over the older ones.
    assert "Entry 0" in wm_text
    # The oldest (i=3, 13 days ago) should have been pushed to overflow.
    assert "Entry 3" not in wm_text


def test_force_promotion_skips_exempt_entries(vault: Path, index: Index) -> None:
    """Entries tagged ``#user``, ``#high-signal``, or ``#decision`` must
    NOT be force-promoted, even when they're the oldest. Losing the
    pinned identity entry to overflow would break the address+sign
    personality rule on the very next session."""
    _write_tight_settings(vault, soft=300, hard=2_000)
    now = datetime(2026, 4, 27, 10, 0, 0)

    # Oldest entry is the identity pin. Should survive force-promotion.
    _write_working_entry(
        vault,
        when=now - timedelta(days=30),
        tags=["#user", "#high-signal"],
        content="Identity bookends: User Justin. Sign as Pacey emoji.",
    )

    # Newer non-exempt entries that should get force-promoted instead.
    for i in range(5):
        _write_working_entry(
            vault,
            when=now - timedelta(days=10 + i),
            tags=["#fact"],
            content=f"Filler {i}: padding text padding text padding text.",
        )

    plan = compact_ops.plan_compaction(vault, index, now=now)
    for cand in plan["candidates"]:
        cand["decision"] = "skip"
    result = compact_ops.apply_compaction(vault, index, plan)

    assert result.overflow_promoted >= 1, (
        "expected non-exempt fillers to overflow to make room"
    )

    wm_text = (vault / WORKING_MEMORY).read_text(encoding="utf-8")
    assert "Identity bookends" in wm_text, (
        "exempt identity entry must survive force-promotion — "
        "personality bookends rely on this"
    )

    # The overflow file should not contain the exempt content.
    overflow = vault / LONG_TERM_DIR / "working-overflow.md"
    if overflow.is_file():
        overflow_text = overflow.read_text(encoding="utf-8")
        assert "Identity bookends" not in overflow_text


def test_force_promotion_halts_when_only_exempt_entries_remain(
    vault: Path, index: Index
) -> None:
    """If after force-promoting every non-exempt entry the body is
    still over the soft cap (e.g. the user has many tagged decisions),
    force-promotion must stop rather than touch exempt content. doctor
    surfaces the situation later as a warning."""
    _write_tight_settings(vault, soft=200, hard=10_000)
    now = datetime(2026, 4, 27, 10, 0, 0)

    # All entries are exempt; total > soft cap.
    for i in range(4):
        _write_working_entry(
            vault,
            when=now - timedelta(days=10 + i),
            tags=["#decision"],
            content=f"Decision {i}: chose option A over B for reason X.",
        )

    plan = compact_ops.plan_compaction(vault, index, now=now)
    for cand in plan["candidates"]:
        cand["decision"] = "skip"
    result = compact_ops.apply_compaction(vault, index, plan)

    # Nothing was force-promoted because everything is exempt.
    assert result.overflow_promoted == 0

    # All four decisions should still be in working memory.
    wm_text = (vault / WORKING_MEMORY).read_text(encoding="utf-8")
    for i in range(4):
        assert f"Decision {i}" in wm_text
