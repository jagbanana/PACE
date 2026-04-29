"""Weekly deep review: archival + wikilink validation + weekly synthesis.

PRD reference: §6.4, §6.10. Like compact, review is a two-step ritual:

1. ``plan_review(root, index)`` walks ``memories/long_term/`` and
   surfaces *archival candidates* matching the §6.10 rules — older than
   90 days, zero refs in the last 60 days, and not carrying any
   retention-exempt tag (``#high-signal``, ``#decision``, ``#user``).
   It also reports broken wikilinks for the user to resolve.

2. The scheduled task LLM reviews the plan, sets each candidate's
   ``decision`` to ``"approve"`` or ``"skip"``, and fills in
   ``weekly_synthesis`` with the prose to write into
   ``memories/long_term/weekly_<YYYY-WW>.md``.
   :func:`apply_review` then physically moves approved files to
   ``memories/archived/``, writes the synthesis note, and re-indexes.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from pace import frontmatter, wikilinks
from pace.index import Index, now_iso
from pace.io import atomic_write_text
from pace.paths import ARCHIVED_DIR, LONG_TERM_DIR

# PRD §6.10 retention exemptions — never auto-archived.
_EXEMPT_TAGS: frozenset[str] = frozenset({"#high-signal", "#decision", "#user"})

# Default thresholds (configurable in pace_config.yaml in a later phase).
_ARCHIVAL_AGE_DAYS = 90
_REF_WINDOW_DAYS = 60
_PREVIEW_CHARS = 240


@dataclass(frozen=True)
class ApplyReviewResult:
    """Outcome of :func:`apply_review` — surfaced through the CLI."""

    archived: int
    skipped: int
    weekly_note_written: bool
    log_path: Path | None


# ---- Plan ------------------------------------------------------------


def plan_review(
    root: Path, index: Index, *, now: datetime | None = None
) -> dict[str, Any]:
    """Build a JSON-serializable review plan for the LLM."""
    now = now or datetime.now()
    candidates = _archival_candidates(root, index, now=now)
    broken = _broken_wikilinks(root, index)

    # Suggest a target path for the weekly synthesis note. ISO week is the
    # natural grouping; collisions with an existing file are rare since
    # review runs once per week.
    iso_year, iso_week, _ = now.isocalendar()
    weekly_path = f"{LONG_TERM_DIR}/weekly_{iso_year}-W{iso_week:02d}.md"

    return {
        "kind": "review_plan",
        "vault_root": str(root.resolve()),
        "generated_at": now_iso(),
        "candidates": candidates,
        "broken_wikilinks": broken,
        "weekly_synthesis_target": weekly_path,
        "weekly_synthesis": None,
    }


def _archival_candidates(
    root: Path, index: Index, *, now: datetime
) -> list[dict[str, Any]]:
    long_term_root = root / LONG_TERM_DIR
    if not long_term_root.is_dir():
        return []

    age_cutoff = now - timedelta(days=_ARCHIVAL_AGE_DAYS)
    out: list[dict[str, Any]] = []

    for path in sorted(long_term_root.rglob("*.md")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        record = index.get_by_path(rel)
        if record is None:
            # Not in index → skip; pace reindex will fix this.
            continue

        try:
            modified = datetime.fromisoformat(record.date_modified)
        except (TypeError, ValueError):
            continue

        if modified > age_cutoff:
            continue

        # Retention exemption: never auto-archive these tags.
        if any(t in _EXEMPT_TAGS for t in record.tags):
            continue

        ref_count = index.reference_count(record.id, since_days=_REF_WINDOW_DAYS)
        if ref_count > 0:
            continue

        rationale = (
            f"date_modified {record.date_modified} is older than "
            f"{_ARCHIVAL_AGE_DAYS} days and refs in last {_REF_WINDOW_DAYS}d = 0"
        )
        out.append(
            {
                "id": f"archive-{len(out)}",
                "action": "archive",
                "decision": "pending",
                "path": rel,
                "title": record.title,
                "tags": record.tags,
                "date_modified": record.date_modified,
                "ref_count_in_window": ref_count,
                "content_preview": _preview(record.body),
                "rationale": rationale,
            }
        )
    return out


def _broken_wikilinks(root: Path, index: Index) -> list[dict[str, Any]]:
    """Walk the vault for ``[[Targets]]`` that don't resolve.

    Reports source path and the unresolved target so the LLM can
    surface them through next session's ``pace_status`` (or so the user
    can fix them by hand).
    """
    paths_to_ids = index.all_paths_with_ids()
    broken: list[dict[str, Any]] = []

    for rel, _fid in sorted(paths_to_ids.items()):
        full = root / rel
        if not full.is_file():
            continue
        _, body = frontmatter.parse(full.read_text(encoding="utf-8"))
        for link in wikilinks.extract(body):
            if wikilinks.resolve(link.target, paths_to_ids) is None:
                broken.append({"source_path": rel, "target": link.target})
    return broken


def _preview(body: str) -> str:
    cleaned = re.sub(r"\s+", " ", body).strip()
    if len(cleaned) <= _PREVIEW_CHARS:
        return cleaned
    return cleaned[:_PREVIEW_CHARS].rstrip() + "…"


# ---- Apply -----------------------------------------------------------


def apply_review(
    root: Path, index: Index, plan: dict[str, Any]
) -> ApplyReviewResult:
    """Execute approved archivals and write the weekly synthesis note.

    Candidates with ``decision == "approve"`` and ``action == "archive"``
    are moved from ``memories/long_term/`` to ``memories/archived/``;
    the index is updated to reflect the new path and ``kind="archived"``.

    If ``plan["weekly_synthesis"]`` is a non-empty string, it's written
    to ``plan["weekly_synthesis_target"]`` as a long-term note. The LLM
    is responsible for the prose; we just persist what it produced.
    """
    if plan.get("kind") != "review_plan":
        raise ValueError(f"Expected review_plan; got {plan.get('kind')!r}.")

    archived = 0
    skipped = 0
    log_lines: list[str] = [f"# pace review run @ {now_iso()}"]

    for cand in plan.get("candidates", []):
        if cand.get("action") != "archive":
            continue
        if cand.get("decision") != "approve":
            skipped += 1
            log_lines.append(f"- skip ({cand.get('decision')}): {cand['path']}")
            continue

        src_rel = cand["path"]
        src_path = root / src_rel
        if not src_path.is_file():
            log_lines.append(f"- skip (missing): {src_rel}")
            skipped += 1
            continue

        # Preserve the filename; archived/<original-stem>.md.
        archived_dir = root / ARCHIVED_DIR
        archived_dir.mkdir(parents=True, exist_ok=True)
        dest_path = _unique_destination(archived_dir, src_path.name)
        shutil.move(str(src_path), str(dest_path))

        # Re-index: drop old row, insert with kind=archived at new path.
        index.delete_file(src_rel)
        new_rel = dest_path.relative_to(root).as_posix()
        _reindex_archived(root, dest_path, new_rel, index)

        archived += 1
        log_lines.append(f"- archive: {src_rel} → {new_rel}")

    weekly_note_written = False
    synthesis = plan.get("weekly_synthesis")
    target = plan.get("weekly_synthesis_target")
    if synthesis and target:
        weekly_path = root / target
        _write_weekly_note(weekly_path, synthesis, index, root)
        weekly_note_written = True
        log_lines.append(f"- weekly note: {target}")

    if plan.get("broken_wikilinks"):
        log_lines.append("- broken wikilinks (surface to user):")
        for entry in plan["broken_wikilinks"]:
            log_lines.append(f"    {entry['source_path']} → [[{entry['target']}]]")

    index.set_config("last_review", now_iso())

    log_path = _write_run_log(root, "review", log_lines)
    return ApplyReviewResult(
        archived=archived,
        skipped=skipped,
        weekly_note_written=weekly_note_written,
        log_path=log_path,
    )


def _unique_destination(archived_dir: Path, name: str) -> Path:
    """Avoid clobbering an existing archived/<name>.md by suffixing."""
    candidate = archived_dir / name
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    n = 1
    while True:
        alt = archived_dir / f"{stem}_{n}{suffix}"
        if not alt.exists():
            return alt
        n += 1


def _reindex_archived(root: Path, path: Path, rel: str, index: Index) -> None:
    fm, body = frontmatter.parse(path.read_text(encoding="utf-8"))
    index.upsert_file(
        path=rel,
        kind="archived",
        title=str(fm.get("title") or path.stem),
        body=body,
        date_created=str(fm.get("date_created", now_iso())),
        date_modified=str(fm.get("date_modified", now_iso())),
        tags=list(fm.get("tags") or []),
    )


def _write_weekly_note(
    weekly_path: Path, synthesis: str, index: Index, root: Path
) -> None:
    weekly_path.parent.mkdir(parents=True, exist_ok=True)
    fm = {
        "title": weekly_path.stem.replace("_", " ").title(),
        "kind": "long_term",
        "date_created": now_iso(),
        "date_modified": now_iso(),
        "tags": ["#weekly-synthesis"],
    }
    body = synthesis if synthesis.endswith("\n") else synthesis + "\n"
    atomic_write_text(weekly_path, frontmatter.dump(fm, body))

    rel = weekly_path.relative_to(root).as_posix()
    index.upsert_file(
        path=rel,
        kind="long_term",
        title=str(fm["title"]),
        body=body,
        date_created=str(fm["date_created"]),
        date_modified=str(fm["date_modified"]),
        tags=list(fm["tags"]),
    )


# ---- Logging --------------------------------------------------------


def _write_run_log(root: Path, kind: str, lines: list[str]) -> Path:
    logs_dir = root / "system" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    log_path = logs_dir / f"{kind}_{stamp}.log"
    atomic_write_text(log_path, "\n".join(lines) + "\n")
    return log_path
