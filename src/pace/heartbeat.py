"""Heartbeat — proactive check-in scanner.

The heartbeat runs as a Cowork scheduled task, on the cadence and
working-hours window the user opted into during onboarding. It's the
PACE answer to "what could I usefully resurface for the user right
now?" without being naggy.

Three signals feed the plan:

1. **Date triggers** — pending followups whose ``trigger_value`` date
   has arrived. Deterministic, the easy case.

2. **Stale commitments** — entries in ``working_memory.md`` (or recent
   project notes) that *look* like commitments ("I'll …", "we should …",
   "TODO:", "let's plan …") and haven't seen a follow-up entry in N
   days. Heuristic; the LLM judges before applying.

3. **Patterns** — repeated captures that suggest a stable preference
   the user might want codified, or people mentioned multiple times
   without yet being in long-term memory. Heuristic; the LLM judges.

The orchestrator follows the same plan/apply ritual as
:mod:`pace.compact` and :mod:`pace.review`:

- :func:`plan_heartbeat` builds an advisory JSON plan with candidates
  marked ``decision="pending"``.
- The scheduled task LLM reviews, sets each candidate to ``"approve"``
  or ``"skip"``, and may rewrite the body.
- :func:`apply_heartbeat` materializes approved candidates as ready
  followups and flips ripe pending date triggers to ready.

The "I'm outside working hours / under the cadence" guard is enforced
by :func:`should_run`. Cowork's cron may fire more often than the user
actually wants; this guard makes the heartbeat safe to register at any
cadence Cowork supports.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

from pace import followups as fu_ops
from pace import frontmatter
from pace import settings as pace_settings
from pace.entries import split as split_entries
from pace.index import Index, now_iso
from pace.io import atomic_write_text
from pace.paths import WORKING_MEMORY

# Last-run sentinel lives in the index config rather than its own file —
# keeps the system/ directory tidy and survives reindex cleanly.
_LAST_HEARTBEAT_KEY = "last_heartbeat"

# Words that flag an entry as commitment-shaped. Lower-cased; matched
# against entry body. Loose on purpose — the LLM filters noise; we
# surface candidates.
_COMMITMENT_PHRASES: tuple[str, ...] = (
    "todo:",
    "todo ",
    "i'll ",
    "i will ",
    "we'll ",
    "we will ",
    "let's ",
    "lets ",
    "we should ",
    "i should ",
    "follow up",
    "follow-up",
    "circle back",
    "remind me",
    "next week",
    "by friday",
    "by monday",
    "by tuesday",
    "by wednesday",
    "by thursday",
    "deadline",
    "before the",
)

# Tags that mark an entry as already resolved / not a stale candidate.
_RESOLVED_TAGS: frozenset[str] = frozenset({"#done", "#resolved"})

_DAY_NAMES: tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


# ---- Run-window guard ------------------------------------------------


@dataclass(frozen=True)
class RunDecision:
    """Why :func:`should_run` allowed or blocked a run."""

    run: bool
    reason: str


def should_run(
    settings: pace_settings.Settings,
    *,
    last_run_iso: str | None,
    now: datetime | None = None,
) -> RunDecision:
    """Decide whether the heartbeat should fire right now.

    Three checks: feature flag, working-hours window, cadence gap.
    Returns a structured decision so the scheduled-task prompt can
    surface the reason in the run log.
    """
    now = now or datetime.now()

    if not settings.heartbeat_enabled:
        return RunDecision(run=False, reason="heartbeat_disabled")

    day = _DAY_NAMES[now.weekday()]
    if day not in settings.heartbeat_days:
        return RunDecision(run=False, reason=f"outside_working_days ({day})")

    start = _parse_hhmm(settings.heartbeat_start)
    end = _parse_hhmm(settings.heartbeat_end)
    cur = time(now.hour, now.minute)
    if not (start <= cur < end):
        return RunDecision(
            run=False,
            reason=(
                f"outside_working_hours ("
                f"{settings.heartbeat_start}-{settings.heartbeat_end})"
            ),
        )

    if last_run_iso:
        try:
            last = datetime.fromisoformat(last_run_iso)
        except ValueError:
            last = None
        if last is not None:
            gap = now - last
            cadence = timedelta(minutes=settings.heartbeat_cadence_minutes)
            if gap < cadence:
                return RunDecision(
                    run=False,
                    reason=(
                        f"under_cadence (gap={int(gap.total_seconds() // 60)}m, "
                        f"min={settings.heartbeat_cadence_minutes}m)"
                    ),
                )

    return RunDecision(run=True, reason="ok")


def _parse_hhmm(s: str) -> time:
    h, m = s.split(":", 1)
    return time(int(h), int(m))


# ---- Plan ------------------------------------------------------------


def plan_heartbeat(
    root: Path,
    index: Index,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a JSON-serializable heartbeat plan for the LLM to review.

    The plan never writes anything. ``apply_heartbeat`` does that after
    the LLM marks each candidate ``approve`` / ``skip``.
    """
    now = now or datetime.now()
    settings = pace_settings.load(root)

    last_run = index.get_config(_LAST_HEARTBEAT_KEY)
    decision = should_run(settings, last_run_iso=last_run, now=now)

    plan: dict[str, Any] = {
        "kind": "heartbeat_plan",
        "vault_root": str(root.resolve()),
        "generated_at": now_iso(),
        "run": decision.run,
        "skip_reason": None if decision.run else decision.reason,
        "ripe_date_triggers": [],
        "stale_candidates": [],
        "pattern_candidates": [],
    }

    if not decision.run:
        return plan

    # 1) Date triggers ready to flip pending → ready.
    plan["ripe_date_triggers"] = [
        {
            "id": fu.id,
            "decision": "pending",
            "body": fu.body,
            "trigger_value": fu.trigger_value,
            "project": fu.project,
            "priority": fu.priority,
        }
        for fu in fu_ops.evaluate_date_triggers(root, now=now)
    ]

    # 2) Stale commitment candidates from working memory.
    plan["stale_candidates"] = _stale_candidates(
        root, age_days=settings.heartbeat_stale_age_days, now=now
    )

    # 3) Pattern candidates from recent captures.
    plan["pattern_candidates"] = _pattern_candidates(
        root,
        index,
        min_repeats=settings.heartbeat_pattern_min_repeats,
        now=now,
    )

    return plan


def _stale_candidates(
    root: Path, *, age_days: int, now: datetime
) -> list[dict[str, Any]]:
    """Find commitment-shaped working-memory entries older than ``age_days``
    with no newer same-project / same-tag entry to suggest follow-through.
    """
    wm_path = root / WORKING_MEMORY
    if not wm_path.is_file():
        return []
    _, body = frontmatter.parse(wm_path.read_text(encoding="utf-8"))
    entries = split_entries(body)
    if not entries:
        return []

    cutoff = now - timedelta(days=age_days)
    out: list[dict[str, Any]] = []
    for i, entry in enumerate(entries):
        if entry.timestamp >= cutoff:
            continue
        if any(t in _RESOLVED_TAGS for t in entry.tags):
            continue
        text = entry.body.lower()
        if not any(p in text for p in _COMMITMENT_PHRASES):
            continue
        # Has a newer entry with overlapping tags suggested follow-through?
        relevant_tags = {t for t in entry.tags if t.startswith("#")}
        has_followthrough = False
        for later in entries[i + 1 :]:
            if later.timestamp <= entry.timestamp:
                continue
            if relevant_tags & set(later.tags):
                has_followthrough = True
                break
        if has_followthrough:
            continue

        age = (now - entry.timestamp).days
        out.append(
            {
                "id": f"stale-{i}",
                "decision": "pending",
                "source_heading": entry.heading,
                "body_excerpt": entry.body.strip()[:240],
                "tags": list(entry.tags),
                "age_days": age,
                "rationale": (
                    f"Commitment-shape phrase + age {age}d ≥ "
                    f"{age_days}d threshold + no newer same-tag entry."
                ),
            }
        )
    return out


def _pattern_candidates(
    root: Path,
    index: Index,
    *,
    min_repeats: int,
    now: datetime,
) -> list[dict[str, Any]]:
    """Surface repeated captures the LLM might want to consolidate.

    Heuristic v0.2 — two flavors:

    * **Repeated person mentions.** Same proper-noun-ish token appears
      ``min_repeats`` or more times across recent working-memory
      entries, but isn't yet in ``memories/long_term/people.md``.
    * **Repeated decisions.** Recent entries tagged ``#decision`` that
      share a high-overlap of words with each other — candidate for a
      preference write-up.
    """
    wm_path = root / WORKING_MEMORY
    if not wm_path.is_file():
        return []
    _, body = frontmatter.parse(wm_path.read_text(encoding="utf-8"))
    entries = split_entries(body)
    if not entries:
        return []

    # Look back ~14 days; older noise can't reasonably still be hot.
    horizon = now - timedelta(days=14)
    recent = [e for e in entries if e.timestamp >= horizon]

    out: list[dict[str, Any]] = []

    # ----- repeated person mentions
    # Two-word capitalized names only ("Sasha Reyes"). Single capitalized
    # words at sentence start (e.g. "Spoke", "Met", "Today") are too noisy
    # to match reliably without a full English NLP stack — keeping the
    # heuristic strict here means false-positives stay low at the cost of
    # missing first-name-only mentions. Acceptable for v0.2.
    name_re = re.compile(r"\b([A-Z][a-z]{2,})\s+([A-Z][a-z]{2,})\b")
    name_counts: Counter[str] = Counter()
    for e in recent:
        for m in name_re.finditer(e.body):
            first = m.group(1)
            second = m.group(2)
            if first.lower() in _STOPWORD_PROPERS:
                continue
            if second.lower() in _STOPWORD_PROPERS:
                continue
            name_counts[f"{first} {second}"] += 1

    # Already in long_term/people.md?
    people_path = root / "memories" / "long_term" / "people.md"
    known_people_text = ""
    if people_path.is_file():
        known_people_text = people_path.read_text(encoding="utf-8").lower()

    for name, count in name_counts.most_common(10):
        if count < min_repeats:
            break
        if name.lower() in known_people_text:
            continue
        out.append(
            {
                "id": f"pattern-person-{_slug(name)}",
                "decision": "pending",
                "kind": "person_repeat",
                "subject": name,
                "occurrences": count,
                "rationale": (
                    f"'{name}' appears {count}× in recent working memory "
                    f"but isn't in memories/long_term/people.md yet — "
                    f"worth capturing them as a #person?"
                ),
            }
        )

    # ----- repeated decisions
    decisions = [
        e for e in recent if any(t in {"#decision", "#preference"} for t in e.tags)
    ]
    if len(decisions) >= min_repeats:
        # Bucket by overlapping word sets. Only surface if there's a real
        # cluster — single decisions on different topics aren't a pattern.
        clusters = _cluster_by_overlap(
            [_keyword_set(e.body) for e in decisions], threshold=0.4
        )
        for indices in clusters:
            if len(indices) < min_repeats:
                continue
            cluster_entries = [decisions[i] for i in indices]
            keywords = sorted(
                {
                    w
                    for e in cluster_entries
                    for w in _keyword_set(e.body)
                }
            )[:8]
            out.append(
                {
                    "id": f"pattern-decision-{_slug('-'.join(keywords[:3]))}",
                    "decision": "pending",
                    "kind": "decision_repeat",
                    "occurrences": len(cluster_entries),
                    "shared_keywords": keywords,
                    "headings": [e.heading for e in cluster_entries],
                    "rationale": (
                        f"{len(cluster_entries)} decision/preference "
                        f"entries share keywords {keywords[:3]} — "
                        f"candidate for a consolidated preference."
                    ),
                }
            )

    # Use index for parity-check; not required to compute candidates,
    # but we keep the parameter so the signature is stable across
    # later versions that may want it.
    _ = index

    return out


_STOPWORD_PROPERS: frozenset[str] = frozenset(
    {
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
    }
)


_KEYWORD_RE = re.compile(r"[A-Za-z]{4,}")


def _keyword_set(s: str) -> set[str]:
    """Lower-cased word set of length ≥ 4. Crude but effective for
    overlap clustering on short prose."""
    return {w.lower() for w in _KEYWORD_RE.findall(s)}


def _cluster_by_overlap(
    sets: list[set[str]], *, threshold: float
) -> list[list[int]]:
    """Greedy clustering by Jaccard overlap. Each input is added to the
    first existing cluster whose representative has overlap ≥
    ``threshold``; otherwise it starts a new cluster."""
    clusters: list[list[int]] = []
    representatives: list[set[str]] = []
    for i, s in enumerate(sets):
        if not s:
            continue
        placed = False
        for c, rep in zip(clusters, representatives, strict=False):
            denom = len(s | rep) or 1
            if len(s & rep) / denom >= threshold:
                c.append(i)
                placed = True
                break
        if not placed:
            clusters.append([i])
            representatives.append(s)
    return clusters


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "x"


# ---- Apply -----------------------------------------------------------


@dataclass(frozen=True)
class HeartbeatResult:
    """Outcome of :func:`apply_heartbeat`. Surfaced via CLI / scheduled
    task log."""

    ripe_promoted: int
    stale_created: int
    pattern_created: int
    skipped: int
    log_path: Path | None
    skipped_run: bool = False
    skip_reason: str | None = None


def apply_heartbeat(
    root: Path,
    index: Index,
    plan: dict[str, Any],
    *,
    now: datetime | None = None,
) -> HeartbeatResult:
    """Materialize approved candidates from a heartbeat plan.

    Reads ``plan["ripe_date_triggers"]``, ``["stale_candidates"]``, and
    ``["pattern_candidates"]``; for each item with ``decision="approve"``,
    creates the corresponding followup (or flips the pending date
    trigger to ready). Updates ``last_heartbeat``.
    """
    if plan.get("kind") != "heartbeat_plan":
        raise ValueError(
            f"Expected heartbeat_plan; got {plan.get('kind')!r}."
        )

    now = now or datetime.now()

    if not plan.get("run", True):
        # The plan was an "I shouldn't run" no-op. We still record the
        # last_heartbeat so the cadence guard sees forward progress.
        index.set_config(_LAST_HEARTBEAT_KEY, now.isoformat(timespec="seconds"))
        return HeartbeatResult(
            ripe_promoted=0,
            stale_created=0,
            pattern_created=0,
            skipped=0,
            log_path=None,
            skipped_run=True,
            skip_reason=plan.get("skip_reason"),
        )

    log_lines: list[str] = [f"# pace heartbeat run @ {now_iso()}"]
    ripe_promoted = 0
    stale_created = 0
    pattern_created = 0
    skipped = 0

    # 1) Flip ripe pending → ready.
    for cand in plan.get("ripe_date_triggers", []):
        if cand.get("decision") != "approve":
            skipped += 1
            log_lines.append(
                f"- skip ripe ({cand.get('decision')}): {cand.get('id')!r}"
            )
            continue
        updated = fu_ops.update_status(root, cand["id"], status="ready")
        if updated is None:
            skipped += 1
            log_lines.append(f"- ripe id not found: {cand['id']!r}")
            continue
        ripe_promoted += 1
        log_lines.append(f"- ripe → ready: {cand['id']}")

    # 2) Stale commitments: each approved candidate becomes a new
    #    'stale' followup, ready immediately.
    for cand in plan.get("stale_candidates", []):
        if cand.get("decision") != "approve":
            skipped += 1
            continue
        body = cand.get("body") or cand.get("body_excerpt") or ""
        fu = fu_ops.add_followup(
            root,
            body=body,
            trigger="stale",
            trigger_value=cand.get("source_heading", ""),
            priority=cand.get("priority", "normal"),
            tags=list(cand.get("tags") or []),
            now=now,
        )
        stale_created += 1
        log_lines.append(f"- stale → followup {fu.id}")

    # 3) Patterns: each approved candidate becomes a new 'pattern'
    #    followup, ready immediately.
    for cand in plan.get("pattern_candidates", []):
        if cand.get("decision") != "approve":
            skipped += 1
            continue
        body = cand.get("body") or cand.get("rationale") or ""
        fu = fu_ops.add_followup(
            root,
            body=body,
            trigger="pattern",
            trigger_value=cand.get("kind", ""),
            priority=cand.get("priority", "normal"),
            now=now,
        )
        pattern_created += 1
        log_lines.append(f"- pattern → followup {fu.id}")

    index.set_config(_LAST_HEARTBEAT_KEY, now.isoformat(timespec="seconds"))

    log_path = _write_run_log(root, log_lines)
    return HeartbeatResult(
        ripe_promoted=ripe_promoted,
        stale_created=stale_created,
        pattern_created=pattern_created,
        skipped=skipped,
        log_path=log_path,
    )


def _write_run_log(root: Path, lines: list[str]) -> Path:
    logs_dir = root / "system" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    log_path = logs_dir / f"heartbeat_{stamp}.log"
    atomic_write_text(log_path, "\n".join(lines) + "\n")
    return log_path


__all__ = [
    "HeartbeatResult",
    "RunDecision",
    "apply_heartbeat",
    "plan_heartbeat",
    "should_run",
]
