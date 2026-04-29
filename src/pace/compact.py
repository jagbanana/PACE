"""Daily compaction: plan generation and approved-plan application.

PRD reference: §6.3, §6.10. The compaction loop is a two-step ritual:

1. ``plan_compaction(root, index)`` walks ``working_memory.md`` and
   surfaces *promotion candidates* — entries that meet the rules in
   §6.10. It also lists projects that saw working-memory activity for
   the LLM to consider rewriting summaries (no apply action needed; the
   LLM uses ``pace_capture`` for those updates).

2. The scheduled task LLM reviews the plan, sets each candidate's
   ``decision`` to ``"approve"`` or ``"skip"``, and may set ``topic``
   to override the suggested target. The edited plan is then handed
   back to :func:`apply_compaction`, which physically moves entries
   from working memory into ``memories/long_term/<topic>.md`` and
   re-indexes both files.

Phase 5 implements promotions only. Merging redundant entries is
deferred to a future phase — it requires semantic judgment the LLM
performs ad-hoc with file edits during the scheduled task.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from pace import frontmatter
from pace.entries import Entry, append, remove, split
from pace.index import Index, now_iso
from pace.io import atomic_write_text
from pace.paths import LONG_TERM_DIR, WORKING_MEMORY

# Tag-driven topic suggestions. When the LLM doesn't override, these are
# safe defaults that group related facts in the same long_term file.
_TAG_TO_TOPIC: dict[str, str] = {
    "#person": "people",
    "#user": "user",
    "#business": "business",
    "#identifier": "identifiers",
    "#date": "dates",
    "#preference": "preferences",
    "#decision": "decisions",
    "#high-signal": "high-signal",
}

# Tags that make an entry a promotion candidate even without references —
# inherently long-term content per PRD §6.10.
_LONG_TERM_TAGS: frozenset[str] = frozenset({"#person", "#identifier", "#decision", "#business"})

# Default "old enough to consider promoting" cutoff in days, per §6.10.
_PROMOTION_AGE_DAYS = 7

# Regex to detect identifier-shaped content (emails, account numbers,
# recurring date markers). Loose on purpose — better to surface a
# candidate the LLM declines than miss a real one.
_IDENTIFIER_RE = re.compile(
    r"\b(?:[\w.\-]+@[\w.\-]+\.\w+"          # email
    r"|\b\d{4}-\d{2}-\d{2}\b"               # ISO date
    r"|\b[A-Z]{2,}-\d{2,}\b)",              # KEBAB-12 codenames
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ApplyResult:
    """Outcome of :func:`apply_compaction` — surfaced through the CLI."""

    promoted: int
    skipped: int
    log_path: Path | None


# ---- Plan ------------------------------------------------------------


def plan_compaction(root: Path, index: Index, *, now: datetime | None = None) -> dict[str, Any]:
    """Build a JSON-serializable compaction plan for the LLM to review.

    The plan is *advisory* — every candidate has ``decision="pending"``
    until the LLM (or a test) sets it to ``"approve"`` or ``"skip"``.
    """
    now = now or datetime.now()
    candidates = _promotion_candidates(root, now=now)
    active = _projects_with_recent_activity(root, index, now=now)

    return {
        "kind": "compact_plan",
        "vault_root": str(root.resolve()),
        "generated_at": now_iso(),
        "candidates": candidates,
        "active_projects_with_activity": active,
    }


def _promotion_candidates(root: Path, *, now: datetime) -> list[dict[str, Any]]:
    wm_path = root / WORKING_MEMORY
    if not wm_path.is_file():
        return []
    text = wm_path.read_text(encoding="utf-8")
    _, body = frontmatter.parse(text)
    entries = split(body)
    if not entries:
        return []

    out: list[dict[str, Any]] = []
    cutoff = now - timedelta(days=_PROMOTION_AGE_DAYS)
    for i, entry in enumerate(entries):
        rationale_parts: list[str] = []

        old_enough = entry.timestamp < cutoff
        long_term_tagged = any(t in _LONG_TERM_TAGS for t in entry.tags)
        identifier_match = bool(_IDENTIFIER_RE.search(entry.body))

        if long_term_tagged:
            tag_list = ", ".join(t for t in entry.tags if t in _LONG_TERM_TAGS)
            rationale_parts.append(f"tagged {tag_list} — inherently long-term")
        if old_enough:
            age_days = (now - entry.timestamp).days
            rationale_parts.append(f"age {age_days} days ≥ {_PROMOTION_AGE_DAYS}-day cutoff")
        if identifier_match:
            rationale_parts.append("contains identifier-shaped content")

        # Promotion rule (PRD §6.10): age + reference, OR long-term tag,
        # OR identifier match. We surface "age + reference" as a soft
        # candidate (rationale notes age; LLM judges the rest).
        if not (long_term_tagged or identifier_match or old_enough):
            continue

        suggested_topic = _suggest_topic(entry.tags)
        out.append(
            {
                "id": f"promote-{i}",
                "action": "promote",
                "decision": "pending",
                "source_path": WORKING_MEMORY,
                "source_heading": entry.heading,
                "content": entry.body,
                "tags": entry.tags,
                "suggested_topic": suggested_topic,
                "topic": None,
                "rationale": "; ".join(rationale_parts) or "default candidate",
            }
        )
    return out


def _projects_with_recent_activity(
    root: Path, index: Index, *, now: datetime, since_days: int = 1
) -> list[dict[str, Any]]:
    """Projects whose summary or notes were touched in the last day.

    The LLM uses this as a checklist for deciding which project summaries
    need a refresh. There's no apply action — the LLM updates summaries
    via ``pace_capture(kind="project_summary", ...)``.
    """
    cutoff = (now - timedelta(days=since_days)).isoformat()
    rows = index._conn.execute(  # noqa: SLF001 — internal helper, intentional
        """
        SELECT project, COUNT(*) AS n, MAX(date_modified) AS most_recent
        FROM files
        WHERE kind IN ('project_summary', 'project_note')
          AND project IS NOT NULL
          AND date_modified >= ?
        GROUP BY project
        ORDER BY most_recent DESC
        """,
        (cutoff,),
    ).fetchall()
    return [
        {
            "project": row["project"],
            "recent_entry_count": row["n"],
            "most_recent_modified": row["most_recent"],
            "summary_path": f"projects/{row['project']}/summary.md",
        }
        for row in rows
    ]


def _suggest_topic(tags: list[str]) -> str:
    """Pick the long-term topic file that best matches an entry's tags.

    First match in tag order wins; falls back to the most-frequent tag's
    topic, then to ``"general"``.
    """
    for tag in tags:
        if tag in _TAG_TO_TOPIC:
            return _TAG_TO_TOPIC[tag]
    if tags:
        # Most-frequent tag (rare in single entries, but defensible).
        top = Counter(tags).most_common(1)[0][0]
        return top.lstrip("#") or "general"
    return "general"


# ---- Apply -----------------------------------------------------------


def apply_compaction(
    root: Path,
    index: Index,
    plan: dict[str, Any],
) -> ApplyResult:
    """Execute the approved promotions in ``plan``.

    Reads each candidate where ``decision == "approve"``, removes the
    entry from ``working_memory.md``, appends it (with original heading
    and body) to ``memories/long_term/<topic>.md`` (or whichever ``topic``
    the LLM chose), and re-indexes both files. Updates the
    ``last_compact`` config and writes a human-readable log line.

    Candidates with ``decision == "skip"`` or ``"pending"`` are ignored.
    """
    if plan.get("kind") != "compact_plan":
        raise ValueError(f"Expected compact_plan; got {plan.get('kind')!r}.")

    promoted = 0
    skipped = 0

    wm_path = root / WORKING_MEMORY
    wm_text = wm_path.read_text(encoding="utf-8") if wm_path.is_file() else ""
    wm_fm, wm_body = frontmatter.parse(wm_text) if wm_text else ({}, "")
    wm_dirty = False

    log_lines: list[str] = [f"# pace compact run @ {now_iso()}"]

    for cand in plan.get("candidates", []):
        if cand.get("action") != "promote":
            continue
        decision = cand.get("decision", "pending")
        if decision != "approve":
            skipped += 1
            log_lines.append(
                f"- skip ({decision}): {cand.get('source_heading')!r}"
            )
            continue

        topic = cand.get("topic") or cand.get("suggested_topic") or "general"
        slug = _slugify_topic(topic)
        target_rel = f"{LONG_TERM_DIR}/{slug}.md"
        target_path = root / target_rel

        # Remove from working_memory.
        new_wm_body, removed = remove(wm_body, cand["source_heading"])
        if removed is None:
            log_lines.append(
                f"- skip (heading not found): {cand['source_heading']!r}"
            )
            skipped += 1
            continue

        wm_body = new_wm_body
        wm_dirty = True

        # Append to long_term/<slug>.md.
        _append_to_long_term(target_path, removed, topic=topic)
        # Re-index the long-term file with the merged body.
        _reindex_long_term(root, target_path, index)

        promoted += 1
        log_lines.append(
            f"- promote → {target_rel}: {cand['source_heading']!r}"
        )

    if wm_dirty:
        wm_fm["date_modified"] = now_iso()
        atomic_write_text(wm_path, frontmatter.dump(wm_fm, wm_body))
        # Re-index working memory with its trimmed body.
        index.upsert_file(
            path=WORKING_MEMORY,
            kind="working",
            title=str(wm_fm.get("title", "Working Memory")),
            body=wm_body,
            date_created=str(wm_fm.get("date_created", now_iso())),
            date_modified=str(wm_fm.get("date_modified")),
            tags=list(wm_fm.get("tags") or []),
        )

    index.set_config("last_compact", now_iso())

    log_path = _write_run_log(root, "compact", log_lines)
    return ApplyResult(promoted=promoted, skipped=skipped, log_path=log_path)


def _append_to_long_term(target_path: Path, entry: Entry, *, topic: str) -> None:
    """Append ``entry`` to a long_term/<topic>.md, creating it if needed."""
    if target_path.is_file():
        text = target_path.read_text(encoding="utf-8")
        fm, body = frontmatter.parse(text)
    else:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        fm = {
            "title": _humanize(topic),
            "kind": "long_term",
            "date_created": now_iso(),
            "date_modified": now_iso(),
            "tags": [],
        }
        body = ""

    new_body = append(body, entry)
    fm["date_modified"] = now_iso()
    file_tags = sorted(set(fm.get("tags") or []) | set(entry.tags))
    fm["tags"] = file_tags
    atomic_write_text(target_path, frontmatter.dump(fm, new_body))


def _reindex_long_term(root: Path, target_path: Path, index: Index) -> None:
    text = target_path.read_text(encoding="utf-8")
    fm, body = frontmatter.parse(text)
    rel = target_path.relative_to(root).as_posix()
    index.upsert_file(
        path=rel,
        kind="long_term",
        title=str(fm.get("title") or _humanize(target_path.stem)),
        body=body,
        date_created=str(fm.get("date_created", now_iso())),
        date_modified=str(fm.get("date_modified", now_iso())),
        tags=list(fm.get("tags") or []),
    )


# ---- Logging ---------------------------------------------------------


def _write_run_log(root: Path, kind: str, lines: list[str]) -> Path:
    logs_dir = root / "system" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    log_path = logs_dir / f"{kind}_{stamp}.log"
    atomic_write_text(log_path, "\n".join(lines) + "\n")
    return log_path


# ---- Slug / title helpers -------------------------------------------


def _slugify_topic(topic: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", topic).strip("-").lower()
    return s or "general"


def _humanize(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", " ", s).strip().title() or "General"
