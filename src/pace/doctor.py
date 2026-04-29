"""Vault health checks (PRD §6.7, §7.2).

``pace doctor`` and ``pace_status`` both surface the same set of issues —
this module is the single source of truth so the CLI and the MCP
server can't drift.

Checks performed:

* ``onedrive_virtualized``  — vault files marked online-only by OneDrive
  (Windows attribute ``RECALL_ON_DATA_ACCESS``); SQLite mmap fails
  silently when the DB is virtualized (PRD §7.2).
* ``db_integrity``          — ``PRAGMA integrity_check`` on the SQLite
  index.
* ``index_drift``           — files whose on-disk mtime is newer than
  the indexed ``date_modified`` (user edited in Obsidian without
  running ``pace reindex``).
* ``broken_wikilinks``      — ``[[Targets]]`` that don't resolve to a
  vault file. Surfaced by next ``pace_status`` so the user can fix.
* ``conflicted_copies``     — OneDrive ``* (Conflicted Copy *).md``.
  Never auto-resolved; the user picks the canonical version.
* ``scheduled_task_stale``  — ``last_compact``/``last_review``
  timestamps older than expected slots, or never recorded — proxy for
  "scheduled tasks aren't firing".

Resolution is always user-initiated. Doctor never deletes files,
mutates frontmatter, or reorganizes the vault.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from pace import frontmatter, wikilinks
from pace import settings as pace_settings
from pace.index import Index
from pace.paths import INDEX_DB, WORKING_MEMORY

# Windows file-attribute flags. Python's ``os.stat_result.st_file_attributes``
# exposes the raw DWORD on Windows; the names below come from
# winnt.h. Defined as plain ints so they work on every platform even
# though we only consult them on Windows.
_RECALL_ON_DATA_ACCESS = 0x00400000  # cloud-only, retrieved on read
_RECALL_ON_OPEN = 0x00040000         # cloud-only, retrieved on open
_OFFLINE = 0x00001000                # legacy offline marker

# Tolerance for index-drift detection. File mtime resolution varies (FAT
# rounds to 2s; NTFS to 100ns; OneDrive sync can shift mtimes by a second
# or two). 60 seconds is generous without masking real drift.
_DRIFT_TOLERANCE = timedelta(seconds=60)

# Scheduled-task freshness windows. last_compact should fire daily; if
# nothing's been recorded for 36+ hours we assume it isn't firing.
# last_review fires weekly; 9 days is a "you missed at least one slot"
# threshold.
_COMPACT_FRESHNESS = timedelta(hours=36)
_REVIEW_FRESHNESS = timedelta(days=9)


@dataclass(frozen=True)
class HealthIssue:
    """One row in the doctor report."""

    severity: str           # 'info' | 'warning' | 'error'
    code: str               # short stable identifier
    message: str            # human-readable summary
    detail: str | None = None
    fix_hint: str | None = None


@dataclass(frozen=True)
class HealthReport:
    """Aggregate result of a doctor run, from one run of :func:`run_all`."""

    root: Path
    issues: list[HealthIssue]

    @property
    def healthy(self) -> bool:
        """True iff every issue is informational (none worse than info)."""
        return all(i.severity == "info" for i in self.issues)

    @property
    def errors(self) -> list[HealthIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[HealthIssue]:
        return [i for i in self.issues if i.severity == "warning"]


# ---- Top-level ---------------------------------------------------------


def run_all(root: Path, index: Index, *, now: datetime | None = None) -> HealthReport:
    """Run every check against ``root``/``index`` and return a report."""
    now = now or datetime.now()
    settings = pace_settings.load(root)
    issues: list[HealthIssue] = []
    issues.extend(check_onedrive_virtualized(root))
    issues.extend(check_db_integrity(index))
    issues.extend(check_index_drift(root, index))
    issues.extend(check_broken_wikilinks(root, index))
    issues.extend(check_conflicted_copies(root))
    issues.extend(check_scheduled_task_freshness(index, now=now))
    issues.extend(check_working_memory_size(root, settings))
    return HealthReport(root=root.resolve(), issues=issues)


# ---- Individual checks -------------------------------------------------


def check_onedrive_virtualized(root: Path) -> list[HealthIssue]:
    """Flag vault files OneDrive has set to cloud-only.

    PACE writes SQLite via mmap, which fails silently against a
    virtualized file. The fix is "Always keep on this device" set on
    the vault root in File Explorer (PRD §7.2).
    """
    if sys.platform != "win32":
        return []

    issues: list[HealthIssue] = []
    # Check the vault root directory plus the two files most exposed to
    # the bug: the SQLite DB and working_memory.md. If those are local,
    # everything else under the same dir typically is too.
    candidates = [root, root / INDEX_DB, root / WORKING_MEMORY]
    seen_offenders: list[str] = []
    for path in candidates:
        if not path.exists():
            continue
        try:
            attrs = path.stat().st_file_attributes  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            continue
        if attrs & (_RECALL_ON_DATA_ACCESS | _RECALL_ON_OPEN | _OFFLINE):
            seen_offenders.append(str(path))

    if seen_offenders:
        issues.append(
            HealthIssue(
                severity="error",
                code="onedrive-virtualized",
                message=(
                    "OneDrive has marked vault files as online-only. "
                    "SQLite mmap will fail."
                ),
                detail="; ".join(seen_offenders),
                fix_hint=(
                    "Right-click the vault folder in File Explorer and "
                    "choose 'Always keep on this device'."
                ),
            )
        )
    return issues


def check_db_integrity(index: Index) -> list[HealthIssue]:
    """Run ``PRAGMA integrity_check`` and surface any non-ok rows."""
    try:
        problems = index.integrity_check()
    except Exception as exc:  # pragma: no cover — defensive
        return [
            HealthIssue(
                severity="error",
                code="db-integrity-failed",
                message="Could not run integrity check on the SQLite index.",
                detail=str(exc),
                fix_hint=(
                    "Run `pace reindex` to rebuild from disk. If the issue "
                    "persists, delete system/pace_index.db and run "
                    "`pace reindex`."
                ),
            )
        ]
    if not problems:
        return []
    return [
        HealthIssue(
            severity="error",
            code="db-corruption",
            message="SQLite integrity_check reported issues.",
            detail="; ".join(problems),
            fix_hint=(
                "Run `pace reindex` to rebuild. If issues persist, "
                "delete system/pace_index.db and re-run reindex."
            ),
        )
    ]


def check_index_drift(root: Path, index: Index) -> list[HealthIssue]:
    """Flag files whose on-disk mtime is newer than the indexed
    ``date_modified``.

    The most common cause is the user editing a markdown file directly
    in Obsidian without running ``pace reindex``. We don't auto-fix —
    the LLM may have stale snippets in context, so it's a real warning.
    """
    drift: list[str] = []
    for rel in index.all_paths():
        full = root / rel
        if not full.is_file():
            # Stale row; reindex will clean it up. Counted in a separate
            # check would be redundant — not flagged here.
            continue
        record = index.get_by_path(rel)
        if record is None:
            continue
        try:
            mtime = datetime.fromtimestamp(full.stat().st_mtime)
            indexed = datetime.fromisoformat(record.date_modified)
        except (TypeError, ValueError, OSError):
            continue
        if mtime > indexed + _DRIFT_TOLERANCE:
            drift.append(rel)
    if not drift:
        return []
    return [
        HealthIssue(
            severity="warning",
            code="index-drift",
            message=f"{len(drift)} file(s) modified on disk after last index.",
            detail=", ".join(drift),
            fix_hint="Run `pace reindex` to refresh.",
        )
    ]


def check_broken_wikilinks(root: Path, index: Index) -> list[HealthIssue]:
    """Identify ``[[Targets]]`` that don't resolve to a vault file.

    Surfaced through ``pace_status`` so the model raises them with the
    user. The model never auto-fixes wikilinks — it asks.
    """
    paths_to_ids = index.all_paths_with_ids()
    broken: list[str] = []
    for rel in sorted(paths_to_ids):
        full = root / rel
        if not full.is_file():
            continue
        try:
            _, body = frontmatter.parse(full.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for link in wikilinks.extract(body):
            if wikilinks.resolve(link.target, paths_to_ids) is None:
                broken.append(f"{rel} → [[{link.target}]]")
    if not broken:
        return []
    return [
        HealthIssue(
            severity="warning",
            code="broken-wikilinks",
            message=f"{len(broken)} wikilink(s) don't resolve to a vault file.",
            detail="; ".join(broken[:10]) + ("…" if len(broken) > 10 else ""),
            fix_hint=(
                "Either fix the link target or capture the missing entry. "
                "PACE never auto-creates files for broken wikilinks."
            ),
        )
    ]


def check_conflicted_copies(root: Path) -> list[HealthIssue]:
    """OneDrive sometimes writes ``* (Conflicted Copy *).md`` siblings.

    The user must pick a canonical version; doctor never deletes them.
    Files under ``memories/archived/`` are skipped — the user has
    already handled those by archiving.
    """
    archived_root = (root / "memories" / "archived").resolve()
    found: list[str] = []
    for md in root.rglob("*.md"):
        if not md.is_file() or "Conflicted Copy" not in md.name:
            continue
        try:
            md.resolve().relative_to(archived_root)
            continue  # under archived/, treat as resolved
        except ValueError:
            pass
        found.append(md.relative_to(root).as_posix())
    found.sort()
    if not found:
        return []
    return [
        HealthIssue(
            severity="error",
            code="conflicted-copies",
            message=(
                f"OneDrive produced {len(found)} conflicted-copy file(s). "
                "Resolve before continuing — PACE never picks a winner."
            ),
            detail=", ".join(found),
            fix_hint=(
                "Diff the conflicted copy against the canonical file, "
                "merge by hand, then `pace archive <conflicted-path>` to "
                "preserve the loser."
            ),
        )
    ]


def check_scheduled_task_freshness(
    index: Index, *, now: datetime | None = None
) -> list[HealthIssue]:
    """Flag stale ``last_compact``/``last_review`` timestamps.

    Phase 6 can't talk to Cowork's task scheduler directly, but a stale
    timestamp is the same observable as a missing/paused task. The
    daily compact should run ≤ 36h ago; weekly review ≤ 9 days ago.

    Day-1 vaults are exempt: if the vault is younger than the freshness
    window, the never-run warning is suppressed. Otherwise the model
    would nag the user about scheduled tasks for the entire first day.
    """
    now = now or datetime.now()
    vault_age = _vault_age(index, now=now)

    issues: list[HealthIssue] = []
    for key, freshness, label in (
        ("last_compact", _COMPACT_FRESHNESS, "Daily compaction"),
        ("last_review", _REVIEW_FRESHNESS, "Weekly review"),
    ):
        raw = index.get_config(key)
        if raw is None:
            # Suppress on day-1 vaults: if the vault hasn't been around
            # long enough for a scheduled run to have happened, "never
            # ran" is expected, not a failure.
            if vault_age is not None and vault_age <= freshness:
                continue
            issues.append(
                HealthIssue(
                    severity="warning",
                    code=f"{key.replace('_', '-')}-never",
                    message=f"{label} has never run.",
                    fix_hint=(
                        "Check Cowork's scheduled-task UI to confirm "
                        "the task is registered and not paused."
                    ),
                )
            )
            continue
        try:
            last = datetime.fromisoformat(raw)
        except (TypeError, ValueError):
            continue
        elapsed = now - last
        if elapsed > freshness:
            issues.append(
                HealthIssue(
                    severity="warning",
                    code=f"{key.replace('_', '-')}-stale",
                    message=(
                        f"{label} hasn't run in {elapsed.days}d "
                        f"{elapsed.seconds // 3600}h."
                    ),
                    detail=f"last run: {raw}",
                    fix_hint=(
                        "Open Cowork at least once during the scheduled "
                        "window. If still stale next session, check the "
                        "task in Cowork's scheduled-task UI."
                    ),
                )
            )
    return issues


def _vault_age(index: Index, *, now: datetime) -> timedelta | None:
    """How long the vault has existed, per ``vault_created_at`` in config."""
    raw = index.get_config("vault_created_at")
    if raw is None:
        return None
    try:
        created = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None
    return now - created


def check_working_memory_size(
    root: Path, settings: pace_settings.Settings
) -> list[HealthIssue]:
    """Flag working memory above the configured soft / hard char budgets.

    The soft cap is what compaction force-promotes against; if the
    body is over it, daily compaction either hasn't run or didn't have
    enough qualifying material to trim. Either way, the user (or the
    next scheduled run) should know. The hard cap is the threshold at
    which ``pace_status`` truncates the body for context-window safety.
    """
    wm_path = root / WORKING_MEMORY
    if not wm_path.is_file():
        return []
    try:
        text = wm_path.read_text(encoding="utf-8")
        _, body = frontmatter.parse(text)
    except (OSError, ValueError):
        return []

    size = len(body)
    if size <= settings.working_memory_soft_chars:
        return []

    over_hard = size > settings.working_memory_hard_chars
    severity = "error" if over_hard else "warning"
    return [
        HealthIssue(
            severity=severity,
            code="working-memory-oversize",
            message=(
                f"Working memory body is {size:,} chars "
                f"(soft target {settings.working_memory_soft_chars:,}, "
                f"hard cap {settings.working_memory_hard_chars:,})."
            ),
            detail=(
                "pace_status truncates the returned body when over the "
                "hard cap; older content stays on disk and is searchable."
                if over_hard
                else None
            ),
            fix_hint=(
                "Run the daily-compaction scheduled task (or `pace compact "
                "--plan` then `pace compact --apply`). The apply step "
                "force-promotes oldest entries to long-term storage until "
                "the body is under the soft target."
            ),
        )
    ]


# ---- Serialization -----------------------------------------------------


def issue_to_dict(issue: HealthIssue) -> dict[str, str | None]:
    """Convert a :class:`HealthIssue` to a JSON-friendly dict."""
    return {
        "severity": issue.severity,
        "code": issue.code,
        "message": issue.message,
        "detail": issue.detail,
        "fix_hint": issue.fix_hint,
    }


def report_to_warnings(report: HealthReport) -> list[str]:
    """Render report into the flat strings ``pace_status`` returns.

    The MCP shape is intentionally simple — the model just wants
    "raise these to the user". One string per non-info issue.
    """
    out: list[str] = []
    for issue in report.issues:
        if issue.severity == "info":
            continue
        line = f"[{issue.severity}] {issue.message}"
        if issue.detail:
            line += f" ({issue.detail})"
        if issue.fix_hint:
            line += f" — {issue.fix_hint}"
        out.append(line)
    return out
